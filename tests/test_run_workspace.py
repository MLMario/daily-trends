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


def test_new_run_creates_x_directory(tmp_run_dir: Path) -> None:
    # A run always has somewhere for the X scraper to write, even with no
    # X accounts configured — the x/ directory exists from initialization.
    workspace = RunWorkspace.new_run(tmp_run_dir)

    assert (workspace.path / "x").is_dir()


def test_x_posts_path_sits_under_x_dir(tmp_run_dir: Path) -> None:
    # The X scraper's raw output follows the same per-source convention as
    # news/articles.json and vendor_blogs/posts.json.
    workspace = RunWorkspace.new_run(tmp_run_dir)

    assert workspace.x_posts == workspace.path / "x" / "posts.json"
