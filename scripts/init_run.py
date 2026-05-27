"""Pre-flight + new run.

Loads `.env` (if present), verifies config.json + credentials/oauth_client.json
exist, and — when `creators/accounts.json[x]` is non-empty — that BRIGHT_DATA_KEY
is set. Then creates runs/<run_id>/ and prints the run_id to stdout. Non-zero
exit + stderr message on any missing prerequisite, before any fetch.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from scripts.lib.preflight import load_dotenv, missing_prerequisites, x_handles
from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.json"
CLIENT_FILE = REPO_ROOT / "credentials" / "oauth_client.json"
ACCOUNTS = REPO_ROOT / "creators" / "accounts.json"
ENV_FILE = REPO_ROOT / ".env"
RUNS_ROOT = REPO_ROOT / "runs"


def _read_accounts(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    load_dotenv(ENV_FILE)

    missing = missing_prerequisites(
        config_exists=CONFIG.exists(),
        client_exists=CLIENT_FILE.exists(),
        x_accounts=x_handles(_read_accounts(ACCOUNTS)),
        bright_data_key=os.environ.get("BRIGHT_DATA_KEY"),
    )
    if missing:
        print(f"pre-flight failed — missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    RUNS_ROOT.mkdir(exist_ok=True)
    workspace = RunWorkspace.new_run(RUNS_ROOT)
    print(workspace.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
