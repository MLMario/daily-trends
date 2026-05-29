"""Thin client over Bright Data's dataset-collection API.

Dataset-agnostic by design: the Instagram Reels dataset (ADR-0002) is the
only caller today, but the X reactivation path described in PRD #24 reuses
this client with a different `dataset_id` and body shape. The three public
methods mirror Bright Data's own pipeline: `trigger` queues a snapshot,
`poll` blocks until the snapshot terminates (ready/failed/etc.), `fetch`
downloads the records.

HTTP shape (verified by tests/integration/test_bright_data_live.py — the
operator-gated live test that is the only mechanical check on the wire
format in this slice):

  POST /datasets/v3/trigger
       ?dataset_id=...&type=discover_new&discover_by=url
       &format=json&include_errors=true
       Authorization: Bearer <BRIGHT_DATA_KEY>
       body: [{...account record...}, ...]
  GET  /datasets/v3/progress/<snapshot_id>
       → {"status": "ready" | "failed" | "running" | ...}
  GET  /datasets/v3/snapshot/<snapshot_id>?format=json
       → [{...reel record...}, ...]

`type=discover_new` is hardcoded — every current and planned caller wants
the discover-new pipeline, not the delivery-snapshot one. Future code that
needs a different type can promote it to a `trigger()` kwarg.
"""

from __future__ import annotations

import os
import time
from typing import Any

import requests

TRIGGER_URL = "https://api.brightdata.com/datasets/v3/trigger"
PROGRESS_URL = "https://api.brightdata.com/datasets/v3/progress"
SNAPSHOT_URL = "https://api.brightdata.com/datasets/v3/snapshot"

# Bright Data progress statuses that mean the snapshot is still in flight.
# Anything else (`ready`, `failed`, …) is terminal and ends `poll()`.
_RUNNING_STATUSES = frozenset({"running", "building", "starting", "collecting"})


class BrightDataClient:
    """Bright Data dataset-API client.

    Constructed eagerly with an API key so the "missing credential" failure
    mode surfaces before any HTTP attempt — the scrape_instagram orchestrator
    catches the RuntimeError and converts it to a single ErrorLog event,
    rather than trying once with no auth and parsing the API's 401 body.
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        key = api_key if api_key is not None else os.environ.get("BRIGHT_DATA_KEY")
        if not key:
            raise RuntimeError(
                "BRIGHT_DATA_KEY missing — set it in the environment or pass api_key=..."
            )
        self._api_key = key

    def _auth_headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def trigger(
        self,
        dataset_id: str,
        body: list[dict[str, Any]],
        *,
        discover_by: str,
        format: str = "json",
        include_errors: bool = True,
    ) -> str:
        """Queue a discover-new snapshot. Returns the snapshot id.

        `body` is the dataset-specific payload (for instagram_reels it's the
        list of `{"url", "num_of_posts", "start_date", "end_date"}` records
        described in ADR-0002). `discover_by` selects the discovery mode —
        `"url"` for instagram_reels.
        """
        params = {
            "dataset_id": dataset_id,
            "type": "discover_new",
            "discover_by": discover_by,
            "format": format,
            "include_errors": "true" if include_errors else "false",
        }
        resp = requests.post(
            TRIGGER_URL,
            params=params,
            headers=self._auth_headers(json_body=True),
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        snapshot_id = payload.get("snapshot_id")
        if not snapshot_id:
            raise RuntimeError(
                f"trigger response missing snapshot_id: {payload!r}"
            )
        return snapshot_id

    def poll(
        self,
        snapshot_id: str,
        *,
        interval_s: int = 30,
        ceiling_s: int = 540,
    ) -> str:
        """Block until the snapshot reaches a terminal status. Returns the status.

        Raises TimeoutError after `ceiling_s` elapsed without termination —
        the orchestrator maps that to an `error` event under step
        `scrape_instagram` per the issue #28 taxonomy. The 540s default
        gives a 9-minute ceiling, comfortably under the 10-minute outer
        tool timeouts the pipeline runs under.
        """
        url = f"{PROGRESS_URL}/{snapshot_id}"
        start = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            if elapsed > ceiling_s:
                raise TimeoutError(
                    f"snapshot {snapshot_id} did not terminate within {ceiling_s}s"
                )
            resp = requests.get(
                url, headers=self._auth_headers(), timeout=60
            )
            resp.raise_for_status()
            payload = resp.json()
            status = payload.get("status") if isinstance(payload, dict) else None
            if status not in _RUNNING_STATUSES:
                return status or "unknown"
            time.sleep(interval_s)

    def fetch(self, snapshot_id: str) -> list[dict[str, Any]]:
        """Download the finished snapshot. Returns the list of records.

        Bright Data returns `[]` for an empty snapshot (zero records in the
        lookback window) and a JSON array otherwise. Anything else surfaces
        as a RuntimeError so the orchestrator can log a clean error.
        """
        resp = requests.get(
            f"{SNAPSHOT_URL}/{snapshot_id}",
            params={"format": "json"},
            headers=self._auth_headers(),
            timeout=120,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            raise RuntimeError(
                f"snapshot {snapshot_id} fetch returned non-list: {type(payload).__name__}"
            )
        return payload
