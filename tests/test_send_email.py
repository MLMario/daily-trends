"""Behavior tests for scripts.send_email attachment gathering.

`gather_attachments` collects the per-run artifacts that ride along with the
Digest email. Each is guarded by an existence check so a slow day (no synthesis
files) or a failed report step simply omits the attachment with no special
casing. report.html is attached when the report subagent wrote it and omitted
otherwise — covering both the slow-day path (report step skipped) and the
report-failure path (subagent produced no readable file).
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.run_workspace import RunWorkspace
from scripts.send_email import gather_attachments


def make_workspace(tmp_path: Path) -> RunWorkspace:
    runs = tmp_path / "runs"
    runs.mkdir()
    return RunWorkspace.new_run(runs)


def names(attachments) -> set[str]:
    return {a.filename for a in attachments}


def test_report_html_attached_when_present(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    ws.trending_topics.write_text(json.dumps({"topics": []}), encoding="utf-8")
    ws.content_recommendations.write_text(json.dumps([]), encoding="utf-8")
    ws.report.write_text("<!doctype html><html></html>", encoding="utf-8")

    attachments = gather_attachments(ws)

    assert "report.html" in names(attachments)
    report = next(a for a in attachments if a.filename == "report.html")
    assert report.content == b"<!doctype html><html></html>"


def test_report_html_omitted_on_slow_day(tmp_path: Path) -> None:
    # Slow day: synthesis files absent and the report step is skipped, so
    # report.html never exists. The attachment list omits it with no error.
    ws = make_workspace(tmp_path)

    attachments = gather_attachments(ws)

    assert "report.html" not in names(attachments)


def test_report_html_omitted_on_report_failure(tmp_path: Path) -> None:
    # Full path ran (synthesis files exist) but the report subagent produced no
    # readable report.html — the existence guard omits it, the others ride.
    ws = make_workspace(tmp_path)
    ws.trending_topics.write_text(json.dumps({"topics": []}), encoding="utf-8")
    ws.content_recommendations.write_text(json.dumps([]), encoding="utf-8")

    attachments = gather_attachments(ws)

    assert "report.html" not in names(attachments)
    # The synthesis files still attach — report omission is isolated.
    assert {"trending_topics.json", "content_recommendations.json"} <= names(attachments)
