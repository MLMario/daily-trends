"""Write the X source's raw posts for a run.

Usage: python -m scripts.scrape_x <run_id>

Thin Bash-callable shell around BrightDataClient + XScraper. Reads
`creators/accounts.json[x]` and `config.json[x_lookback_days]`, computes the
MM-DD-YYYY lookback window (end = today UTC, start = today − lookback), fetches
one snapshot per account, and writes the uniform raw schema to
runs/<run_id>/x/posts.json. When no X accounts are configured it short-circuits
to an empty list and makes no Bright Data call (so BRIGHT_DATA_KEY isn't needed).
All the logic worth testing lives in XScraper; this entry is exercised by the
dry-run / live smoke per the PRD.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib.bright_data_client import BrightDataClient
from scripts.lib.error_log import ErrorLog
from scripts.lib.preflight import load_dotenv, x_handles
from scripts.lib.run_workspace import RunWorkspace
from scripts.lib.x_scraper import XScraper

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
ACCOUNTS = REPO_ROOT / "creators" / "accounts.json"
CONFIG = REPO_ROOT / "config.json"
ENV_FILE = REPO_ROOT / ".env"

DEFAULT_LOOKBACK_DAYS = 1
BRIGHT_DATA_DATE = "%m-%d-%Y"  # Bright Data's MM-DD-YYYY window format


def _lookback_days() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    return int(config.get("x_lookback_days", DEFAULT_LOOKBACK_DAYS))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.scrape_x <run_id>", file=sys.stderr)
        return 2

    workspace = RunWorkspace.existing_run(RUNS_ROOT, argv[1])
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8")) if ACCOUNTS.exists() else None
    handles = x_handles(accounts)

    if not handles:
        posts: list[dict] = []
        note = "0 (no X accounts configured)"
    else:
        load_dotenv(ENV_FILE)  # BRIGHT_DATA_KEY lives in .env; this process must load it
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=_lookback_days())
        scraper = XScraper(
            BrightDataClient(api_key=os.environ["BRIGHT_DATA_KEY"]),
            ErrorLog(workspace.errors),
        )
        posts = scraper.scrape(
            handles,
            start_date=start.strftime(BRIGHT_DATA_DATE),
            end_date=end.strftime(BRIGHT_DATA_DATE),
        )
        note = f"{len(posts)} (from {len(handles)} account(s))"

    workspace.x_posts.write_text(json.dumps(posts, indent=2), encoding="utf-8")
    print(f"x posts: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
