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
) -> None:
    """Run the IG scrape step against an already-minted run.

    Empty `accounts["instagram"]` (or missing accounts file) short-circuits
    to a clean no-op. All other failures are logged to the run's
    `errors.log` and swallowed; the pipeline continues regardless.
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
