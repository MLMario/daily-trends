"""Plain-list email renderer for the slice-2 walking skeleton.

Layout: one block per corpus item with title (linked) + URL line + summary. No
topic cards, no errors section yet — those land in later slices.
"""

from __future__ import annotations

import html
import json
from typing import Iterable

from scripts.lib.run_workspace import RunWorkspace


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _render_item(item: dict) -> str:
    title = _esc(item.get("account_or_outlet", "") or item["url"])
    url = _esc(item["url"])
    text = _esc(item["text"]).replace("\n", "<br>")
    return (
        f'<section style="margin-bottom:1.5em">'
        f'<div><a href="{url}">{title}</a></div>'
        f'<div style="font-size:0.85em;color:#666"><a href="{url}">{url}</a></div>'
        f'<p>{text}</p>'
        f"</section>"
    )


class EmailRenderer:
    def __init__(self, workspace: RunWorkspace) -> None:
        self._ws = workspace

    def render(self, *, run_id: str, corpus: Iterable[dict] | None = None) -> str:
        items = list(corpus) if corpus is not None else json.loads(
            self._ws.corpus.read_text(encoding="utf-8")
        )
        body = "\n".join(_render_item(item) for item in items)
        html_doc = (
            "<!doctype html><html><body "
            'style="font-family:-apple-system,Segoe UI,sans-serif;max-width:720px">'
            f'<h1>daily-trends — Run {_esc(run_id)}</h1>'
            f'<p style="color:#666">{len(items)} item(s)</p>'
            f"{body}"
            "</body></html>"
        )
        self._ws.email_sent.write_text(html_doc, encoding="utf-8")
        return html_doc
