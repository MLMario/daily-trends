"""Union per-source raw fetches into a normalized corpus.json.

Every source is read by the same per-source reader: a (path, source-tag) pair
fed through one normalization routine. Adding IG/X/etc. later is one more entry
in `_sources()` — no source-specific branching, no call-site changes.
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


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _to_corpus_item(record: dict, source: str) -> dict:
    return {
        "id": _stable_id(record["url"]),
        "source": source,
        "account_or_outlet": record.get("source", ""),
        "posted_at": record.get("published_at", ""),
        "text": record.get("summary", "") or "",
        "url": record["url"],
    }


class CorpusNormalizer:
    def __init__(self, workspace: RunWorkspace, error_log: ErrorLog) -> None:
        self._ws = workspace
        self._log = error_log

    def _sources(self) -> list[tuple[Path, str]]:
        return [
            (self._ws.news_articles, "news"),
            (self._ws.vendor_blogs_posts, "vendor_blogs"),
        ]

    def run(self) -> list[dict]:
        items: list[dict] = []
        dropped = 0

        for path, source in self._sources():
            for record in _read_records(path):
                item = _to_corpus_item(record, source)
                if _word_count(item["text"]) < MIN_WORDS:
                    dropped += 1
                    continue
                items.append(item)

        self._ws.corpus.write_text(json.dumps(items, indent=2), encoding="utf-8")
        self._log.log(
            step="normalize",
            severity="info",
            message=f"dropped {dropped} item(s) with word_count < {MIN_WORDS}",
            kind="consequential",
        )
        return items
