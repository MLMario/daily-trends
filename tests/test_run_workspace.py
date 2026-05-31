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


def test_report_path_sits_at_run_root(tmp_run_dir: Path) -> None:
    # report.html is a top-level run artifact, alongside email_sent.html — the
    # report subagent's sole output.
    workspace = RunWorkspace.new_run(tmp_run_dir)

    assert workspace.report == workspace.path / "report.html"


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


def test_instagram_dir_returns_per_account_path_without_mkdir(
    tmp_run_dir: Path,
) -> None:
    # Typed accessor mirrors news_articles / vendor_blogs_posts: pure path,
    # no side effects. The B.3 scrape script will mkdir the per-account
    # subdir when it actually has Reels to write.
    workspace = RunWorkspace.new_run(tmp_run_dir, enable_instagram=True)

    account_path = workspace.instagram_dir("hellovidya")

    assert account_path == workspace.path / "instagram" / "hellovidya"
    assert not account_path.exists()  # path-only, caller mkdirs


def test_instagram_per_reel_paths_compose_account_and_post_id(
    tmp_run_dir: Path,
) -> None:
    # The B.3 scrape + B.4 transcribe writers address each Reel by
    # (account, post_id). The three artifacts share a stem and split by
    # suffix — matches the directory shape the B.1 IG reader already walks.
    workspace = RunWorkspace.new_run(tmp_run_dir, enable_instagram=True)
    account = "hellovidya"
    post_id = "3901640805393815120_51994227"
    account_dir = workspace.instagram_dir(account)

    assert workspace.instagram_meta(account, post_id) == account_dir / f"{post_id}.meta.json"
    assert workspace.instagram_mp4(account, post_id) == account_dir / f"{post_id}.mp4"
    assert (
        workspace.instagram_transcript(account, post_id)
        == account_dir / f"{post_id}.transcript.json"
    )
