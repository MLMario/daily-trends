"""Pre-flight + new run.

Verifies config.json and credentials/oauth_client.json exist, reads
creators/accounts.json to decide whether the IG subtree is needed, then
creates runs/<run_id>/ and prints the run_id to stdout. Non-zero exit +
stderr message on missing prerequisites.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.json"
CLIENT_FILE = REPO_ROOT / "credentials" / "oauth_client.json"
ACCOUNTS = REPO_ROOT / "creators" / "accounts.json"
RUNS_ROOT = REPO_ROOT / "runs"


def create_run(
    *,
    config_path: Path,
    client_path: Path,
    accounts_path: Path,
    runs_root: Path,
) -> RunWorkspace:
    """Run pre-flight, derive IG opt-in from accounts.json, mint workspace.

    Raises FileNotFoundError when config_path or client_path is missing —
    matches the pre-existing CLI pre-flight semantics. Accounts file is
    treated as optional: a missing file is the same as an empty IG list.
    """
    missing = [str(p) for p in (config_path, client_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"pre-flight failed — missing: {', '.join(missing)}"
        )

    enable_instagram = False
    if accounts_path.exists():
        accounts = json.loads(accounts_path.read_text(encoding="utf-8"))
        enable_instagram = bool(accounts.get("instagram"))

    runs_root.mkdir(exist_ok=True)
    return RunWorkspace.new_run(runs_root, enable_instagram=enable_instagram)


def main() -> int:
    try:
        workspace = create_run(
            config_path=CONFIG,
            client_path=CLIENT_FILE,
            accounts_path=ACCOUNTS,
            runs_root=RUNS_ROOT,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(workspace.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
