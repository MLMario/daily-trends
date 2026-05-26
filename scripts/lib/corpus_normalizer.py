"""Union per-source raw fetches into a normalized corpus.json.

Slice 2 reads only runs/<id>/news/articles.json. Adding IG/X/vendor blogs later
is "another reader inside this module" — call sites do not change.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace

MIN_WORDS = 30


def _word_count(text: str) -> int:
    return len(text.split())


def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _read_news(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


class CorpusNormalizer:
    def __init__(self, workspace: RunWorkspace, error_log: ErrorLog) -> None:
        self._ws = workspace
        self._log = error_log

    def run(self) -> list[dict]:
        items: list[dict] = []
        dropped = 0

        for article in _read_news(self._ws.news_articles):
            text = article.get("summary", "") or ""
            if _word_count(text) < MIN_WORDS:
                dropped += 1
                continue
            items.append(
                {
                    "id": _stable_id(article["url"]),
                    "source": "news",
                    "account_or_outlet": article.get("source", ""),
                    "posted_at": article.get("published_at", ""),
                    "text": text,
                    "url": article["url"],
                }
            )

        self._ws.corpus.write_text(json.dumps(items, indent=2), encoding="utf-8")
        self._log.log(
            step="normalize",
            severity="info",
            message=f"dropped {dropped} item(s) with word_count < {MIN_WORDS}",
            kind="consequential",
        )
        return items
