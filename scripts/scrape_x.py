"""Write the X source's raw posts for a run.

Usage: python -m scripts.scrape_x <run_id>

Slice B.2 — opt-in control plane only, no fetch. Reads `creators/accounts.json[x]`
and writes the uniform raw schema to runs/<run_id>/x/posts.json. When no X
accounts are configured it short-circuits to an empty list and makes no Bright
Data call. The actual fetch (BrightDataClient + XScraper) lands in Slice B.3,
filling the non-empty branch below.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.lib.preflight import x_handles
from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
ACCOUNTS = REPO_ROOT / "creators" / "accounts.json"


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
        # Slice B.3 fills the fetch here (BrightDataClient + XScraper per handle).
        posts = []
        note = "0 (fetch not yet implemented — Slice B.3)"

    workspace.x_posts.write_text(json.dumps(posts, indent=2), encoding="utf-8")
    print(f"x posts: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
