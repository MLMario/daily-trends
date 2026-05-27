"""Behavior tests for scripts.lib.error_log.ErrorLog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.error_log import ErrorLog


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_summary_of_empty_or_missing_log_is_empty(tmp_path: Path) -> None:
    # No entries written yet (file never created) — and after creating an empty
    # file too. A summary with nothing to report is empty, so the renderer omits
    # the Errors & Skips section.
    missing = ErrorLog(tmp_path / "errors.log")
    assert missing.summary().is_empty
    assert missing.summary().groups == ()

    created = tmp_path / "created.log"
    created.write_text("", encoding="utf-8")
    assert ErrorLog(created).summary().is_empty


def test_summary_groups_by_step_with_per_step_severity_counts(tmp_path: Path) -> None:
    log = ErrorLog(tmp_path / "errors.log")
    log.log(step="fetch", severity="warning", message="slow source")
    log.log(step="fetch", severity="error", message="source crashed")
    log.log(step="fetch", severity="warning", message="another slow source")
    log.log(step="cluster", severity="error", message="bad output")

    by_step = {g.step: g for g in log.summary().groups}

    assert by_step["fetch"].warning_count == 2
    assert by_step["fetch"].error_count == 1
    assert by_step["cluster"].error_count == 1
    assert by_step["cluster"].warning_count == 0


def test_summary_collects_consequential_info_and_drops_pure_info(tmp_path: Path) -> None:
    log = ErrorLog(tmp_path / "errors.log")
    log.log(step="normalize", severity="error", message="boom")  # keeps step in summary
    log.log(
        step="normalize",
        severity="info",
        message="dropped 4 item(s) with word_count < 30",
        kind="consequential",
    )
    log.log(step="normalize", severity="info", message="stage start 12:00:00")  # pure info

    [group] = log.summary().groups
    assert group.step == "normalize"
    assert group.consequential == ("dropped 4 item(s) with word_count < 30",)
    assert "stage start 12:00:00" not in group.consequential


def test_summary_groups_iterate_in_step_first_seen_order(tmp_path: Path) -> None:
    # Groups follow the order each step first appears in the log (pipeline order),
    # not alphabetical — so the email reads top-to-bottom like the run unfolded.
    log = ErrorLog(tmp_path / "errors.log")
    log.log(step="render", severity="error", message="r")
    log.log(step="normalize", severity="warning", message="n")
    log.log(step="render", severity="warning", message="r2")  # re-touch, no reorder
    log.log(step="fetch", severity="error", message="f")

    assert [g.step for g in log.summary().groups] == ["render", "normalize", "fetch"]


def test_summary_omits_steps_with_only_pure_info_entries(tmp_path: Path) -> None:
    # Stage-boundary timing entries are pure info logged under their own steps.
    # A step that produced nothing but pure info has nothing to report, so it
    # forms no group — and a log of only pure info summarizes as empty.
    log = ErrorLog(tmp_path / "errors.log")
    log.log(step="init_run", severity="info", message="start 12:00:00")
    log.log(step="cluster", severity="info", message="start 12:01:00")
    log.log(step="fetch", severity="warning", message="slow source")

    summary = log.summary()
    assert [g.step for g in summary.groups] == ["fetch"]

    info_only = ErrorLog(tmp_path / "info_only.log")
    info_only.log(step="init_run", severity="info", message="start")
    info_only.log(step="render", severity="info", message="done")
    assert info_only.summary().is_empty


def test_log_writes_a_jsonl_record_with_required_fields(tmp_path: Path) -> None:
    log = ErrorLog(tmp_path / "errors.log")

    log.log(step="normalize", severity="info", message="hello")

    [entry] = read_lines(tmp_path / "errors.log")
    assert entry["step"] == "normalize"
    assert entry["severity"] == "info"
    assert entry["message"] == "hello"
    assert "timestamp" in entry and entry["timestamp"]


def test_log_preserves_insertion_order_and_writes_valid_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "errors.log"
    log = ErrorLog(log_path)

    log.log(step="fetch", severity="info", message="first")
    log.log(step="normalize", severity="warning", message="second")
    log.log(step="render", severity="error", message="third")

    raw = log_path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 3
    entries = [json.loads(line) for line in raw]
    assert [e["message"] for e in entries] == ["first", "second", "third"]


def test_log_omits_optional_fields_when_not_provided(tmp_path: Path) -> None:
    log_path = tmp_path / "errors.log"
    log = ErrorLog(log_path)

    log.log(step="fetch", severity="info", message="plain")

    [entry] = read_lines(log_path)
    assert "item_id" not in entry
    assert "kind" not in entry


def test_log_includes_optional_item_id_and_kind_when_provided(tmp_path: Path) -> None:
    log_path = tmp_path / "errors.log"
    log = ErrorLog(log_path)

    log.log(
        step="normalize",
        severity="info",
        message="dropped 4 short items",
        kind="consequential",
    )
    log.log(
        step="fetch",
        severity="warning",
        message="failed url",
        item_id="abc123",
    )

    a, b = read_lines(log_path)
    assert a["kind"] == "consequential"
    assert "item_id" not in a
    assert b["item_id"] == "abc123"
    assert "kind" not in b
