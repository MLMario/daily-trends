"""Behavior tests for scripts.lib.run_workspace lineage helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.run_workspace import RunWorkspace, lineage_record


def test_lineage_record_carries_source_reused_and_created_at() -> None:
    # A recluster records where its corpus came from and when the new run was
    # minted. The timestamp is injected so the record is deterministic.
    when = datetime(2026, 5, 26, 14, 30, tzinfo=timezone.utc)

    record = lineage_record("2026-05-20T09-15Z", reused=("corpus.json",), now=when)

    assert record == {
        "source_run_id": "2026-05-20T09-15Z",
        "reused": ["corpus.json"],
        "created_at": "2026-05-26T14:30:00+00:00",
    }


def test_lineage_path_sits_at_run_root(tmp_run_dir: Path) -> None:
    # lineage.json is a top-level run artifact, alongside corpus.json.
    workspace = RunWorkspace.new_run(tmp_run_dir)

    assert workspace.lineage == workspace.path / "lineage.json"


def test_new_run_without_instagram_flag_does_not_create_instagram_dir(
    tmp_run_dir: Path,
) -> None:
    # Default conservative — pre-Slice-B callers (init_run today, recluster)
    # construct workspaces without IG; the directory tree must not grow until
    # the operator opts in via creators/accounts.json.
    workspace = RunWorkspace.new_run(tmp_run_dir)

    assert (workspace.path / "news").is_dir()
    assert (workspace.path / "vendor_blogs").is_dir()
    assert not (workspace.path / "instagram").exists()


def test_new_run_with_enable_instagram_creates_instagram_dir(
    tmp_run_dir: Path,
) -> None:
    # Opt-in via init_run when creators/accounts.json[instagram] is non-empty.
    # The IG subtree exists at the run root, peer to news/ and vendor_blogs/.
    workspace = RunWorkspace.new_run(tmp_run_dir, enable_instagram=True)

    assert (workspace.path / "instagram").is_dir()
    assert (workspace.path / "news").is_dir()
    assert (workspace.path / "vendor_blogs").is_dir()
