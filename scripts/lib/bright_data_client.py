"""Bright Data Dataset v3 client for the X (Twitter) posts dataset.

Isolates the provider seam from ADR 0001: the X dataset
(`gd_lwxkxvnf1cynvib9co`) in "discover by profile URL" mode, behind a single
`discover_posts(profile_url, start_date, end_date)` call that hides the
asynchronous **trigger snapshot -> poll until ready -> download -> parse**
dance and owns the `BRIGHT_DATA_KEY` token and all HTTP. A future swap to
another provider stays contained here, exactly as `GmailSender` isolates the
Gmail API.

The HTTP session, poll cadence, and sleep/clock are injectable so the behavior
is testable offline and a never-ready snapshot fails fast (`SnapshotTimeout`)
instead of hanging.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import requests

DATASET_ID = "gd_lwxkxvnf1cynvib9co"
API_ROOT = "https://api.brightdata.com/datasets/v3"

DEFAULT_POLL_INTERVAL = 10.0
DEFAULT_POLL_TIMEOUT = 600.0
DEFAULT_HTTP_TIMEOUT = 60.0


class BrightDataError(Exception):
    """Base error for any Bright Data fetch problem (caught per-account upstream)."""


class SnapshotTimeout(BrightDataError):
    """A snapshot never reached the `ready` state within the poll timeout."""


class SnapshotFailed(BrightDataError):
    """Bright Data reported the snapshot itself failed."""


class BrightDataClient:
    def __init__(
        self,
        *,
        api_key: str,
        dataset_id: str = DATASET_ID,
        session: requests.Session | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        poll_timeout: float = DEFAULT_POLL_TIMEOUT,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._dataset_id = dataset_id
        self._session = session or requests.Session()
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._sleep = sleep
        self._clock = clock

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def discover_posts(
        self, *, profile_url: str, start_date: str, end_date: str
    ) -> list[dict]:
        """Recent posts for one profile in the [start_date, end_date] window.

        `start_date`/`end_date` are MM-DD-YYYY strings (Bright Data's format).
        Returns the raw provider records; mapping to the uniform schema is the
        scraper's job, not the client's.
        """
        snapshot_id = self._trigger(profile_url, start_date, end_date)
        self._poll_until_ready(snapshot_id)
        return self._download(snapshot_id)

    def _trigger(self, profile_url: str, start_date: str, end_date: str) -> str:
        response = self._session.post(
            f"{API_ROOT}/trigger",
            params={
                "dataset_id": self._dataset_id,
                "type": "discover_new",
                "discover_by": "profile_url",
            },
            headers={**self._auth, "Content-Type": "application/json"},
            json=[{"url": profile_url, "start_date": start_date, "end_date": end_date}],
            timeout=DEFAULT_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["snapshot_id"]

    def _poll_until_ready(self, snapshot_id: str) -> None:
        deadline = self._clock() + self._poll_timeout
        while True:
            status = self._progress(snapshot_id)
            if status == "ready":
                return
            if status == "failed":
                raise SnapshotFailed(f"snapshot {snapshot_id} failed")
            if self._clock() >= deadline:
                raise SnapshotTimeout(
                    f"snapshot {snapshot_id} not ready within {self._poll_timeout}s"
                )
            self._sleep(self._poll_interval)

    def _progress(self, snapshot_id: str) -> str:
        response = self._session.get(
            f"{API_ROOT}/progress/{snapshot_id}",
            headers=self._auth,
            timeout=DEFAULT_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("status", "")

    def _download(self, snapshot_id: str) -> list[dict]:
        response = self._session.get(
            f"{API_ROOT}/snapshot/{snapshot_id}",
            params={"format": "json"},
            headers=self._auth,
            timeout=DEFAULT_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload: Any = response.json()
        return payload if isinstance(payload, list) else []
