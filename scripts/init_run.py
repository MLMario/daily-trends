"""Pre-flight + new run.

Verifies config.json and credentials/oauth_client.json exist, then creates
runs/<run_id>/ and prints the run_id to stdout. Non-zero exit + stderr message
on missing prerequisites.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.json"
CLIENT_FILE = REPO_ROOT / "credentials" / "oauth_client.json"
RUNS_ROOT = REPO_ROOT / "runs"


def main() -> int:
    missing = [str(p) for p in (CONFIG, CLIENT_FILE) if not p.exists()]
    if missing:
        print(f"pre-flight failed — missing: {', '.join(missing)}", file=sys.stderr)
        return 1

    RUNS_ROOT.mkdir(exist_ok=True)
    workspace = RunWorkspace.new_run(RUNS_ROOT)
    print(workspace.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
