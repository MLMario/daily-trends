"""Behavior tests for scripts.lib.bright_data_client.BrightDataClient.

The Bright Data Dataset v3 HTTP transport is the only mocked collaborator —
exactly like the Gmail API in test_gmail_sender. A FakeSession scripts the
trigger/progress/snapshot responses in order and records the requests, so the
tests assert the documented request shape and the trigger->poll->download
behavior without a network call. The poll clock and sleep are injected so the
timeout test is instant and never actually waits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from scripts.lib.bright_data_client import (
    BrightDataClient,
    SnapshotTimeout,
)


@dataclass
class FakeResponse:
    _payload: Any
    status_code: int = 200

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")


@dataclass
class RecordedRequest:
    method: str
    url: str
    params: dict | None
    headers: dict | None
    json: Any


@dataclass
class FakeSession:
    """A requests.Session stand-in: returns scripted responses in FIFO order."""

    scripted: list[FakeResponse]
    calls: list[RecordedRequest] = field(default_factory=list)

    def post(self, url, *, params=None, headers=None, json=None, timeout=None):
        self.calls.append(RecordedRequest("POST", url, params, headers, json))
        return self.scripted.pop(0)

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append(RecordedRequest("GET", url, params, headers, None))
        return self.scripted.pop(0)


def make_client(session: FakeSession, **kwargs) -> BrightDataClient:
    # sleep is a no-op and the clock is supplied by tests that need timing.
    kwargs.setdefault("sleep", lambda _seconds: None)
    return BrightDataClient(api_key="test-token", session=session, **kwargs)


def test_discover_posts_triggers_polls_until_ready_then_returns_records() -> None:
    records = [{"url": "https://x.com/karpathy/status/1", "description": "hi"}]
    session = FakeSession(
        scripted=[
            FakeResponse({"snapshot_id": "s_abc"}),
            FakeResponse({"status": "ready"}),
            FakeResponse(records),
        ]
    )

    client = make_client(session)
    result = client.discover_posts(
        profile_url="https://x.com/karpathy",
        start_date="05-26-2026",
        end_date="05-27-2026",
    )

    assert result == records


def test_trigger_request_is_shaped_for_discover_by_profile() -> None:
    session = FakeSession(
        scripted=[
            FakeResponse({"snapshot_id": "s_abc"}),
            FakeResponse({"status": "ready"}),
            FakeResponse([]),
        ]
    )

    make_client(session).discover_posts(
        profile_url="https://x.com/karpathy",
        start_date="05-26-2026",
        end_date="05-27-2026",
    )

    trigger = session.calls[0]
    assert trigger.method == "POST"
    assert trigger.url.endswith("/datasets/v3/trigger")
    assert trigger.params["dataset_id"] == "gd_lwxkxvnf1cynvib9co"
    assert trigger.params["discover_by"] == "profile_url"
    assert trigger.headers["Authorization"] == "Bearer test-token"
    assert trigger.json == [
        {
            "url": "https://x.com/karpathy",
            "start_date": "05-26-2026",
            "end_date": "05-27-2026",
        }
    ]


def test_poll_loop_waits_for_snapshot_readiness_before_downloading() -> None:
    records = [{"url": "https://x.com/karpathy/status/1"}]
    session = FakeSession(
        scripted=[
            FakeResponse({"snapshot_id": "s_abc"}),
            FakeResponse({"status": "running"}),
            FakeResponse({"status": "running"}),
            FakeResponse({"status": "ready"}),
            FakeResponse(records),
        ]
    )
    sleeps: list[float] = []
    client = make_client(session, sleep=sleeps.append, poll_interval=10.0)

    result = client.discover_posts(
        profile_url="https://x.com/karpathy", start_date="05-26-2026", end_date="05-27-2026"
    )

    assert result == records
    # polled three times (running, running, ready), sleeping the interval between each
    progress_calls = [c for c in session.calls if "/progress/" in c.url]
    assert len(progress_calls) == 3
    assert sleeps == [10.0, 10.0]
    # the download only happens after readiness — it is the final call
    assert "/snapshot/" in session.calls[-1].url


def test_snapshot_that_never_readies_raises_timeout_instead_of_hanging() -> None:
    session = FakeSession(
        scripted=[
            FakeResponse({"snapshot_id": "s_abc"}),
            FakeResponse({"status": "running"}),
            FakeResponse({"status": "running"}),
            FakeResponse({"status": "running"}),
        ]
    )
    # clock: deadline computed at t=0 (+5s); first check at t=0 (under), second at t=100 (over)
    times = iter([0.0, 0.0, 100.0])
    client = make_client(
        session, clock=lambda: next(times), poll_timeout=5.0, poll_interval=10.0
    )

    with pytest.raises(SnapshotTimeout):
        client.discover_posts(
            profile_url="https://x.com/karpathy",
            start_date="05-26-2026",
            end_date="05-27-2026",
        )

    # it never reached the download endpoint
    assert all("/snapshot/" not in c.url for c in session.calls)
