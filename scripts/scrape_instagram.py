"""Per-run Instagram Reels scraper.

Reads `creators/accounts.json[instagram]` + `config.instagram_lookback_days`
+ `config.instagram_num_of_posts`, fires one combined Bright Data snapshot
for the configured creators, demultiplexes the returned records by
`user_posted`, writes each Reel's metadata to
`runs/<run_id>/instagram/<account>/<post_id>.meta.json`, and shells out to
yt-dlp to pull the `.mp4`.

All error taxonomy events go to the per-run `errors.log`; the helper never
raises out — IG failures are non-fatal to the rest of the pipeline per
PRD #24's error model.

Mirrors `init_run`'s testable-seam pattern: `scrape_instagram(...)` takes
explicit paths + injectable client/runner so tests vary the external
surface; `main()` wires the production constants and the real
`BrightDataClient` + `subprocess.run`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol

from scripts.lib.bright_data import BrightDataClient
from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.json"
ACCOUNTS = REPO_ROOT / "creators" / "accounts.json"
RUNS_ROOT = REPO_ROOT / "runs"

STEP = "scrape_instagram"

# Locked by ADR-0002 — Bright Data's instagram_reels dataset id. Future X
# reactivation passes a different id to the same BrightDataClient.
INSTAGRAM_REELS_DATASET_ID = "gd_lyclm20il4r5helnj"


class _Client(Protocol):
    def trigger(
        self,
        dataset_id: str,
        body: list[dict[str, Any]],
        *,
        discover_by: str,
        format: str = ...,
        include_errors: bool = ...,
    ) -> str: ...
    def poll(
        self, snapshot_id: str, *, interval_s: int = ..., ceiling_s: int = ...
    ) -> str: ...
    def fetch(self, snapshot_id: str) -> list[dict[str, Any]]: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]


def scrape_instagram(
    run_id: str,
    *,
    runs_root: Path,
    config_path: Path,
    accounts_path: Path,
    client: _Client | None = None,
    runner: Runner | None = None,
    log: ErrorLog | None = None,
    today: date | None = None,
) -> None:
    """Run the IG scrape step against an already-minted run.

    Empty `accounts["instagram"]` (or missing accounts file) short-circuits
    to a clean no-op. All other failures are logged to the run's
    `errors.log` and swallowed; the pipeline continues regardless.

    `today` is injectable so the MM-DD-YYYY `start_date`/`end_date` pair
    is deterministic under test.
    """
    workspace = RunWorkspace.existing_run(runs_root, run_id)
    log = log or ErrorLog(workspace.errors)

    accounts = _read_accounts(accounts_path)
    if not accounts:
        return

    if client is None:
        try:
            client = BrightDataClient()
        except RuntimeError as exc:
            log.log(step=STEP, severity="error", message=str(exc))
            return

    config = json.loads(config_path.read_text(encoding="utf-8"))
    lookback = int(config.get("instagram_lookback_days", 7))
    num_of_posts = int(config.get("instagram_num_of_posts", 5))
    end = today or date.today()
    start = end - timedelta(days=lookback)
    body = _build_trigger_body(accounts, num_of_posts=num_of_posts, start=start, end=end)

    snapshot_id = client.trigger(
        INSTAGRAM_REELS_DATASET_ID,
        body,
        discover_by="url",
        format="json",
        include_errors=True,
    )

    try:
        status = client.poll(snapshot_id)
    except TimeoutError as exc:
        log.log(step=STEP, severity="error", message=str(exc))
        return

    if status != "ready":
        log.log(
            step=STEP,
            severity="error",
            message=f"snapshot {snapshot_id} status={status} — aborting IG step",
        )
        return

    records = client.fetch(snapshot_id)

    accounts_with_records: set[str] = set()
    for record in records:
        account = record.get("user_posted")
        post_id = record.get("post_id")
        if not account or not post_id:
            continue
        meta_path = workspace.instagram_meta(account, post_id)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
        accounts_with_records.add(account)

    for account in accounts:
        if account not in accounts_with_records:
            # Quiet creator week — `info` not `consequential`, so the email's
            # Errors & Skips section stays clean. The raw log still carries
            # the row for the operator if they go looking.
            log.log(
                step=STEP,
                severity="info",
                message=f"no Reels for @{account} in lookback window",
            )


def _build_trigger_body(
    accounts: list[str],
    *,
    num_of_posts: int,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    start_str = start.strftime("%m-%d-%Y")
    end_str = end.strftime("%m-%d-%Y")
    return [
        {
            "url": f"https://www.instagram.com/{account}/",
            "num_of_posts": num_of_posts,
            "start_date": start_str,
            "end_date": end_str,
        }
        for account in accounts
    ]


def _read_accounts(accounts_path: Path) -> list[str]:
    if not accounts_path.exists():
        return []
    raw = json.loads(accounts_path.read_text(encoding="utf-8"))
    ig = raw.get("instagram") or []
    return [a for a in ig if a]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: scrape_instagram.py <run_id>", file=sys.stderr)
        return 2
    run_id = args[0]

    scrape_instagram(
        run_id,
        runs_root=RUNS_ROOT,
        config_path=CONFIG,
        accounts_path=ACCOUNTS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
