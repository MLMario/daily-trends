"""Union per-source raw fetches into a normalized corpus.json.

Every source is read by a reader callable that returns a list of corpus items
already in the shared `{id, source, account_or_outlet, posted_at, text, url}`
shape. News and vendor_blogs read a single JSON file each; later sources can
walk a directory tree, compose text from multiple files, or drop records of
their own (logging per-item warnings) — `run()` stays source-agnostic and
applies only the shared word-count filter.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace

MIN_WORDS = 30

Reader = Callable[[], list[dict]]


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

    def _sources(self) -> list[Reader]:
        return [self._read_news, self._read_vendor_blogs, self._read_instagram]

    def _read_news(self) -> list[dict]:
        return [_to_corpus_item(r, "news") for r in _read_records(self._ws.news_articles)]

    def _read_vendor_blogs(self) -> list[dict]:
        return [
            _to_corpus_item(r, "vendor_blogs")
            for r in _read_records(self._ws.vendor_blogs_posts)
        ]

    def _read_instagram(self) -> list[dict]:
        ig_root = self._ws.path / "instagram"
        if not ig_root.is_dir():
            return []
        items: list[dict] = []
        for account_dir in sorted(p for p in ig_root.iterdir() if p.is_dir()):
            for meta_path in sorted(account_dir.glob("*.meta.json")):
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                transcript_path = meta_path.with_name(
                    meta_path.name.replace(".meta.json", ".transcript.json")
                )
                transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
                text = transcript["text"]
                description = (meta.get("description") or "").strip()
                if description:
                    text = f"{text}\n\n[Caption: {description}]"
                items.append(
                    {
                        "id": _stable_id(meta["url"]),
                        "source": "instagram",
                        "account_or_outlet": f"@{meta['user_posted']}",
                        "posted_at": meta["date_posted"],
                        "text": text,
                        "url": meta["url"],
                    }
                )
        return items

    def run(self) -> list[dict]:
        items: list[dict] = []
        dropped = 0

        for reader in self._sources():
            for item in reader():
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
