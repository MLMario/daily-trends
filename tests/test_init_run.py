"""Behavior tests for scripts.init_run's accounts-driven IG opt-in.

`init_run.create_run` is the testable seam carved out of `main()` — it
takes explicit paths in and returns the created RunWorkspace. `main()`
itself stays a thin wrapper that wires the REPO_ROOT-relative constants.

These tests pin the bridge between `creators/accounts.json[instagram]`
and `RunWorkspace.new_run(enable_instagram=...)`.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.init_run import create_run


def setup_preflight(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Materialize the two prereq files + an empty runs root.

    Returns (config_path, client_path, runs_root). Tests add an
    `accounts.json` themselves so each can vary its shape.
    """
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    client = tmp_path / "credentials" / "oauth_client.json"
    client.parent.mkdir()
    client.write_text("{}", encoding="utf-8")
    runs_root = tmp_path / "runs"
    return config, client, runs_root


def test_create_run_with_empty_instagram_list_skips_instagram_dir(
    tmp_path: Path,
) -> None:
    # The operator hasn't seeded any IG creators yet — no IG dir should
    # exist in the run, and the news/vendor_blogs Slice A pipeline still
    # works exactly as before.
    config_path, client_path, runs_root = setup_preflight(tmp_path)
    accounts_path = tmp_path / "creators" / "accounts.json"
    accounts_path.parent.mkdir()
    accounts_path.write_text(
        json.dumps({"instagram": [], "x": []}), encoding="utf-8"
    )

    workspace = create_run(
        config_path=config_path,
        client_path=client_path,
        accounts_path=accounts_path,
        runs_root=runs_root,
    )

    assert (workspace.path / "news").is_dir()
    assert (workspace.path / "vendor_blogs").is_dir()
    assert not (workspace.path / "instagram").exists()


def test_create_run_with_populated_instagram_list_creates_instagram_dir(
    tmp_path: Path,
) -> None:
    # One handle in the IG list is enough to flip the flag — the B.3 scrape
    # script downstream will write per-account subdirs under instagram/.
    config_path, client_path, runs_root = setup_preflight(tmp_path)
    accounts_path = tmp_path / "creators" / "accounts.json"
    accounts_path.parent.mkdir()
    accounts_path.write_text(
        json.dumps({"instagram": ["hellovidya"], "x": []}), encoding="utf-8"
    )

    workspace = create_run(
        config_path=config_path,
        client_path=client_path,
        accounts_path=accounts_path,
        runs_root=runs_root,
    )

    assert (workspace.path / "instagram").is_dir()


def test_create_run_without_accounts_file_defaults_to_no_instagram(
    tmp_path: Path,
) -> None:
    # Defensive: a missing creators/accounts.json must not crash pre-flight.
    # It's the same outcome as an empty IG list — no IG subtree created.
    # Protects the Slice A pipeline if the operator deletes / renames the
    # file before B.3 ships.
    config_path, client_path, runs_root = setup_preflight(tmp_path)
    accounts_path = tmp_path / "creators" / "accounts.json"  # never created

    workspace = create_run(
        config_path=config_path,
        client_path=client_path,
        accounts_path=accounts_path,
        runs_root=runs_root,
    )

    assert not (workspace.path / "instagram").exists()


def test_create_run_raises_when_config_missing(tmp_path: Path) -> None:
    # Pre-flight contract preserved — main() prints to stderr + exits 1 by
    # catching this; the helper just signals via exception.
    import pytest

    config_path = tmp_path / "config.json"  # never created
    client_path = tmp_path / "credentials" / "oauth_client.json"
    client_path.parent.mkdir()
    client_path.write_text("{}", encoding="utf-8")
    accounts_path = tmp_path / "creators" / "accounts.json"
    runs_root = tmp_path / "runs"

    with pytest.raises(FileNotFoundError, match="pre-flight failed"):
        create_run(
            config_path=config_path,
            client_path=client_path,
            accounts_path=accounts_path,
            runs_root=runs_root,
        )
