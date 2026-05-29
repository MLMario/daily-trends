"""Live Bright Data integration smoke test — operator-gated merge check.

This is the only mechanical check on the actual HTTP wire shape in
Slice B.3. The unit tests cover the orchestrator (body construction,
demux, error taxonomy) and the BrightDataClient's missing-key guard,
but not the on-the-wire query-string / Bearer-header / JSON-body
shape — that's verified here, end-to-end, against the real API.

Marked `@pytest.mark.live` so the default `pytest` run does not
collect it. Operator runs `pytest -m live` with `BRIGHT_DATA_KEY` set
before merging B.3, per issue #28 + US #29.

Skips cleanly when the key is absent so a stale shell can run
`pytest -m live` without crashing.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.lib.bright_data import BrightDataClient
from scripts.scrape_instagram import INSTAGRAM_REELS_DATASET_ID

REPO_ROOT = Path(__file__).resolve().parents[2]

# The six fields PRD #24's schema mapping pulls from a record. If any of
# them go missing in a future Bright Data API revision, the normalizer
# would silently produce bad corpus items — better to fail this test
# loudly before merge than to debug it through three downstream stages.
REQUIRED_FIELDS = (
    "post_id",
    "url",
    "description",
    "user_posted",
    "date_posted",
    "video_url",
)


def _resolve_api_key() -> str | None:
    """Read BRIGHT_DATA_KEY from process env, falling back to .env.

    Mirrors the feasibility script's `.env` loader so the operator can
    run the live test against the same convention they used during the
    Slice B feasibility study.
    """
    key = os.environ.get("BRIGHT_DATA_KEY")
    if key:
        return key
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("BRIGHT_DATA_KEY="):
            value = line.partition("=")[2].strip()
            return value.strip('"').strip("'") or None
    return None


@pytest.mark.live
def test_bright_data_client_round_trip_against_hellovidya() -> None:
    key = _resolve_api_key()
    if not key:
        pytest.skip("BRIGHT_DATA_KEY not set in env or .env")

    today = date.today()
    body = [
        {
            "url": "https://www.instagram.com/hellovidya/",
            "num_of_posts": 2,
            "start_date": (today - timedelta(days=7)).strftime("%m-%d-%Y"),
            "end_date": today.strftime("%m-%d-%Y"),
        }
    ]

    client = BrightDataClient(api_key=key)
    snapshot_id = client.trigger(
        INSTAGRAM_REELS_DATASET_ID,
        body,
        discover_by="url",
        format="json",
        include_errors=True,
    )
    assert snapshot_id, "trigger returned an empty snapshot_id"

    status = client.poll(snapshot_id)
    assert status == "ready", f"snapshot terminated with status={status!r}"

    records = client.fetch(snapshot_id)
    assert records, "expected at least one Reel for @hellovidya in the last 7 days"

    sample = records[0]
    missing = [f for f in REQUIRED_FIELDS if f not in sample]
    assert not missing, (
        f"Bright Data record is missing required fields: {missing}; "
        f"available keys: {sorted(sample.keys())}"
    )
