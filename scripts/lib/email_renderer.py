"""Email renderer with two paths, selected by the slow-day flag.

Full topic-card path (no skipped_clustering.json): joins trending_topics.json
and content_recommendations.json by topic_id and renders one card per topic
(description + conversation_summary + linked member sources + per-channel
content ideas + rationale). Items that did not cluster land in a one-liner
Other Notable tail. Member references are resolved against corpus.json: each
member_id maps to its corpus item, rendered as a link (account_or_outlet →
url). IDs absent from the corpus are skipped silently.

Light-signal path (skipped_clustering.json present): clustering and
recommendations never ran, so the renderer reads only the skip flag and
corpus.json. It emits no topic cards — just a corpus-size note explaining why
clustering was skipped, followed by the corpus items as one-liners
(account_or_outlet → url, then text).

Both paths close with a shared Errors & Skips tail built from
ErrorLog.summary(): one subsection per step (error count, warning count, then
consequential-info rows as bullets), omitted entirely when the summary is empty.
Pure-info entries (e.g. stage-timing markers) never reach it.
"""

from __future__ import annotations

import html
import json

from scripts.lib.error_log import ErrorLog, ErrorSummary
from scripts.lib.run_workspace import RunWorkspace


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def _render_errors_section(summary: ErrorSummary) -> str:
    if summary.is_empty:
        return ""
    blocks = []
    for group in summary.groups:
        bullets = "".join(f"<li>{_esc(msg)}</li>" for msg in group.consequential)
        bullets_block = f"<ul>{bullets}</ul>" if bullets else ""
        blocks.append(
            '<div style="margin-bottom:1em">'
            f"<h3>{_esc(group.step)}</h3>"
            f"<p>{group.error_count} error(s), {group.warning_count} warning(s)</p>"
            f"{bullets_block}"
            "</div>"
        )
    return (
        '<section style="margin-top:2em;border-top:1px solid #ccc;padding-top:1em">'
        "<h2>Errors &amp; Skips</h2>"
        f"{''.join(blocks)}"
        "</section>"
    )


def _render_members(member_ids: list, corpus_by_id: dict) -> str:
    rows = []
    for member_id in member_ids:
        item = corpus_by_id.get(member_id)
        if item is None:
            continue  # id not in corpus — skip silently
        url = _esc(item.get("url", ""))
        label = _esc(item.get("account_or_outlet", "") or item.get("url", ""))
        rows.append(f'<li><a href="{url}">{label}</a></li>')
    if not rows:
        return ""
    return f'<div style="font-size:0.9em"><strong>Sources:</strong><ul>{"".join(rows)}</ul></div>'


def _render_ideas(ideas: dict) -> str:
    # Iterate the ideas map by key so adding a channel needs no code change.
    rows = "".join(
        f"<li><strong>{_esc(channel)}:</strong> {_esc(idea)}</li>"
        for channel, idea in ideas.items()
    )
    return f"<ul>{rows}</ul>" if rows else ""


def _render_topic_card(topic: dict, recommendation: dict | None, corpus_by_id: dict) -> str:
    name = _esc(topic.get("topic_name", ""))
    description = _esc(topic.get("description", ""))
    summary = _esc(topic.get("conversation_summary", ""))
    members_block = _render_members(topic.get("member_ids", []), corpus_by_id)

    ideas_block = ""
    rationale_block = ""
    if recommendation is not None:
        ideas_block = _render_ideas(recommendation.get("ideas", {}))
        rationale = recommendation.get("rationale", "")
        if rationale:
            rationale_block = f'<p style="color:#666"><em>Why: {_esc(rationale)}</em></p>'

    return (
        '<section style="margin-bottom:2em">'
        f"<h2>{name}</h2>"
        f"<p>{description}</p>"
        f'<p style="color:#444">{summary}</p>'
        f"{members_block}"
        f"{ideas_block}"
        f"{rationale_block}"
        "</section>"
    )


def _render_corpus_one_liners(items: list) -> str:
    if not items:
        return ""
    rows = "".join(
        f'<li><a href="{_esc(item.get("url", ""))}">'
        f'{_esc(item.get("account_or_outlet", "") or item.get("url", ""))}</a>'
        f' — {_esc(item.get("text", ""))}</li>'
        for item in items
    )
    return f'<section style="margin-top:2em"><h2>Other notable</h2><ul>{rows}</ul></section>'


def _render_other_notable(items: list) -> str:
    if not items:
        return ""
    rows = "".join(
        f'<li><a href="{_esc(item.get("url", ""))}">{_esc(item.get("title", ""))}</a>'
        f' — {_esc(item.get("one_line", ""))}</li>'
        for item in items
    )
    return f'<section style="margin-top:2em"><h2>Other notable</h2><ul>{rows}</ul></section>'


class EmailRenderer:
    def __init__(self, workspace: RunWorkspace) -> None:
        self._ws = workspace

    def render(self, *, run_id: str) -> str:
        if self._ws.skipped_clustering.exists():
            return self._render_light_signal(run_id=run_id)
        return self._render_topic_cards(run_id=run_id)

    def _errors_section(self) -> str:
        return _render_errors_section(ErrorLog(self._ws.errors).summary())

    def _render_light_signal(self, *, run_id: str) -> str:
        skip = json.loads(self._ws.skipped_clustering.read_text(encoding="utf-8"))
        reason = _esc(skip.get("reason", ""))
        corpus_size = _esc(str(skip.get("corpus_size", "")))
        note = (
            '<p style="color:#666"><em>'
            f"Clustering skipped: {reason} (corpus size: {corpus_size})."
            "</em></p>"
        )
        corpus = json.loads(self._ws.corpus.read_text(encoding="utf-8"))
        one_liners = _render_corpus_one_liners(corpus)
        html_doc = (
            "<!doctype html><html><body "
            'style="font-family:-apple-system,Segoe UI,sans-serif;max-width:720px">'
            f"<h1>daily-trends — Run {_esc(run_id)}</h1>"
            f"{note}"
            f"{one_liners}"
            f"{self._errors_section()}"
            "</body></html>"
        )
        self._ws.email_sent.write_text(html_doc, encoding="utf-8")
        return html_doc

    def _render_topic_cards(self, *, run_id: str) -> str:
        trending = json.loads(self._ws.trending_topics.read_text(encoding="utf-8"))
        topics = trending.get("topics", [])

        recommendations = json.loads(
            self._ws.content_recommendations.read_text(encoding="utf-8")
        )
        recs_by_topic = {rec["topic_id"]: rec for rec in recommendations}

        corpus = json.loads(self._ws.corpus.read_text(encoding="utf-8"))
        corpus_by_id = {item["id"]: item for item in corpus}

        cards = "\n".join(
            _render_topic_card(
                topic, recs_by_topic.get(topic.get("topic_id")), corpus_by_id
            )
            for topic in topics
        )
        other_notable = _render_other_notable(trending.get("other_notable", []))
        html_doc = (
            "<!doctype html><html><body "
            'style="font-family:-apple-system,Segoe UI,sans-serif;max-width:720px">'
            f"<h1>daily-trends — Run {_esc(run_id)}</h1>"
            f"{cards}"
            f"{other_notable}"
            f"{self._errors_section()}"
            "</body></html>"
        )
        self._ws.email_sent.write_text(html_doc, encoding="utf-8")
        return html_doc
