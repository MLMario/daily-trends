"""Behavior tests for scripts.lib.error_log.ErrorLog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.error_log import ErrorLog


def read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


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
