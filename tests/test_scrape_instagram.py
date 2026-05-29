"""Behavior tests for scripts.scrape_instagram.scrape_instagram.

The helper takes paths + an injectable `BrightDataClient`-shaped client
and a `subprocess.run`-shaped runner so each scenario can vary the
external surface without touching real HTTP or real yt-dlp. Mirrors the
`init_run.create_run` testable-seam pattern.

The fake `BrightDataClient` here is intentional — we own the
client interface and the orchestrator's behaviour is what these tests
pin (body shape, demux, error mapping). HTTP-shape correctness of the
real client is covered by the live integration test.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace
from scripts.scrape_instagram import scrape_instagram


# --- test doubles -----------------------------------------------------------


@dataclass
class FakeClient:
    """Stand-in for BrightDataClient with canned return values per call."""

    trigger_returns: Any = "sid-default"
    poll_returns: Any = "ready"
    fetch_returns: Any = field(default_factory=list)
    trigger_calls: list[dict[str, Any]] = field(default_factory=list)
    poll_calls: list[dict[str, Any]] = field(default_factory=list)
    fetch_calls: list[str] = field(default_factory=list)

    def trigger(
        self,
        dataset_id: str,
        body: list[dict[str, Any]],
        *,
        discover_by: str,
        format: str = "json",
        include_errors: bool = True,
    ) -> str:
        self.trigger_calls.append(
            {
                "dataset_id": dataset_id,
                "body": body,
                "discover_by": discover_by,
                "format": format,
                "include_errors": include_errors,
            }
        )
        if isinstance(self.trigger_returns, Exception):
            raise self.trigger_returns
        return self.trigger_returns

    def poll(self, snapshot_id: str, *, interval_s: int = 30, ceiling_s: int = 540) -> str:
        self.poll_calls.append({"snapshot_id": snapshot_id})
        if isinstance(self.poll_returns, Exception):
            raise self.poll_returns
        return self.poll_returns

    def fetch(self, snapshot_id: str) -> list[dict[str, Any]]:
        self.fetch_calls.append(snapshot_id)
        if isinstance(self.fetch_returns, Exception):
            raise self.fetch_returns
        return self.fetch_returns


@dataclass
class FakeRunner:
    """Stand-in for `subprocess.run`. Returns CompletedProcess objects
    in the order given; each call records its argv for later inspection.
    Test wires `returncode` per attempt to drive the canonical → CDN
    fallback control flow.
    """

    return_codes: list[int] = field(default_factory=lambda: [0])
    calls: list[list[str]] = field(default_factory=list)

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls.append(list(cmd))
        idx = min(len(self.calls) - 1, len(self.return_codes) - 1)
        rc = self.return_codes[idx]
        return subprocess.CompletedProcess(
            args=cmd, returncode=rc, stdout="", stderr=""
        )


# --- fixtures ---------------------------------------------------------------


def _setup_paths(
    tmp_path: Path,
    *,
    accounts: dict[str, list[str]] | None = None,
    config: dict[str, Any] | None = None,
    enable_instagram: bool = True,
) -> tuple[RunWorkspace, Path, Path, Path]:
    """Mint a workspace + matching config/accounts files on disk.

    Returns (workspace, runs_root, config_path, accounts_path).
    """
    runs_root = tmp_path / "runs"
    workspace = RunWorkspace.new_run(runs_root, enable_instagram=enable_instagram)

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            config
            or {"instagram_lookback_days": 7, "instagram_num_of_posts": 5}
        ),
        encoding="utf-8",
    )

    accounts_path = tmp_path / "creators" / "accounts.json"
    accounts_path.parent.mkdir(parents=True, exist_ok=True)
    accounts_path.write_text(
        json.dumps(accounts or {"instagram": ["hellovidya"], "x": []}),
        encoding="utf-8",
    )

    return workspace, runs_root, config_path, accounts_path


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- tests ------------------------------------------------------------------


def test_empty_instagram_list_is_a_clean_no_op(tmp_path: Path) -> None:
    # Slice A's `enable_instagram=False` plumbing means the IG dir won't
    # even exist on disk for these runs, but the orchestrator should
    # still tolerate being called and exit cleanly without touching the
    # client or subprocess.
    workspace, runs_root, config_path, accounts_path = _setup_paths(
        tmp_path,
        accounts={"instagram": [], "x": []},
        enable_instagram=False,
    )
    client = FakeClient()

    def runner_must_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("runner should not be invoked for an empty IG list")

    scrape_instagram(
        workspace.run_id,
        runs_root=runs_root,
        config_path=config_path,
        accounts_path=accounts_path,
        client=client,
        runner=runner_must_not_be_called,
    )

    assert client.trigger_calls == []
    assert client.poll_calls == []
    assert client.fetch_calls == []
    assert _read_log(workspace.errors) == []


def test_missing_bright_data_key_logs_error_and_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Issue #28 error taxonomy: missing BRIGHT_DATA_KEY is `error` under
    # step `scrape_instagram` and aborts the IG step. The helper must
    # build the client itself (client=None) so this path goes through
    # the real BrightDataClient.__init__ guard.
    workspace, runs_root, config_path, accounts_path = _setup_paths(tmp_path)
    monkeypatch.delenv("BRIGHT_DATA_KEY", raising=False)

    def runner_must_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("runner should not run when the key is missing")

    scrape_instagram(
        workspace.run_id,
        runs_root=runs_root,
        config_path=config_path,
        accounts_path=accounts_path,
        client=None,
        runner=runner_must_not_be_called,
    )

    entries = _read_log(workspace.errors)
    assert len(entries) == 1
    [entry] = entries
    assert entry["step"] == "scrape_instagram"
    assert entry["severity"] == "error"
    assert "BRIGHT_DATA_KEY" in entry["message"]


def test_builds_combined_body_one_entry_per_account_mm_dd_yyyy_no_post_type(
    tmp_path: Path,
) -> None:
    # ADR-0002 locks the trigger body shape: one record per creator, MM-DD-YYYY
    # date fields, num_of_posts pulled from config, NO post_type field (the
    # reels dataset is reels-only by definition and rejects post_type).
    # discover_by="url", include_errors=True, format="json" round out the
    # call. Today is injected so the date string is deterministic.
    workspace, runs_root, config_path, accounts_path = _setup_paths(
        tmp_path,
        accounts={"instagram": ["hellovidya", "anothercreator"], "x": []},
        config={"instagram_lookback_days": 7, "instagram_num_of_posts": 3},
    )
    client = FakeClient(fetch_returns=[])  # empty fetch — no per-Reel work
    runner = FakeRunner()

    scrape_instagram(
        workspace.run_id,
        runs_root=runs_root,
        config_path=config_path,
        accounts_path=accounts_path,
        client=client,
        runner=runner,
        today=date(2026, 5, 28),
    )

    assert len(client.trigger_calls) == 1
    [call] = client.trigger_calls
    assert call["discover_by"] == "url"
    assert call["format"] == "json"
    assert call["include_errors"] is True

    body = call["body"]
    assert len(body) == 2
    assert body[0] == {
        "url": "https://www.instagram.com/hellovidya/",
        "num_of_posts": 3,
        "start_date": "05-21-2026",
        "end_date": "05-28-2026",
    }
    assert body[1]["url"] == "https://www.instagram.com/anothercreator/"
    for entry in body:
        assert "post_type" not in entry


def test_records_demuxed_by_user_posted_and_written_to_typed_meta_paths(
    tmp_path: Path,
) -> None:
    # Fetch returns records spanning two accounts; each lands as
    # `<post_id>.meta.json` under its `user_posted` subdir via the typed
    # workspace accessor. Per-account `mkdir` is the writer's job (the
    # workspace gives a path only — symmetric with news / vendor_blogs).
    workspace, runs_root, config_path, accounts_path = _setup_paths(
        tmp_path,
        accounts={"instagram": ["hellovidya", "anothercreator"], "x": []},
    )
    records = [
        {
            "post_id": "post_a",
            "url": "https://www.instagram.com/p/post_a/",
            "user_posted": "hellovidya",
            "description": "first reel",
            "date_posted": "2026-05-27T07:58:56.000Z",
            "video_url": "https://cdn/example/a.mp4",
        },
        {
            "post_id": "post_b",
            "url": "https://www.instagram.com/p/post_b/",
            "user_posted": "anothercreator",
            "description": "second reel",
            "date_posted": "2026-05-26T08:00:00.000Z",
            "video_url": "https://cdn/example/b.mp4",
        },
    ]
    client = FakeClient(fetch_returns=records)
    runner = FakeRunner()  # not asserted on in this commit

    scrape_instagram(
        workspace.run_id,
        runs_root=runs_root,
        config_path=config_path,
        accounts_path=accounts_path,
        client=client,
        runner=runner,
    )

    meta_a = workspace.instagram_meta("hellovidya", "post_a")
    meta_b = workspace.instagram_meta("anothercreator", "post_b")
    assert meta_a.is_file()
    assert meta_b.is_file()
    assert json.loads(meta_a.read_text(encoding="utf-8")) == records[0]
    assert json.loads(meta_b.read_text(encoding="utf-8")) == records[1]
