"""Normalize per-source raw fetches into corpus.json for a given run_id.

Usage: python -m scripts.normalize_corpus <run_id>
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.lib.corpus_normalizer import CorpusNormalizer
from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.normalize_corpus <run_id>", file=sys.stderr)
        return 2

    workspace = RunWorkspace.existing_run(RUNS_ROOT, argv[1])
    log = ErrorLog(workspace.errors)
    items = CorpusNormalizer(workspace, log).run()
    print(f"corpus item count: {len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
