"""Behavior tests for scripts.lib.corpus_normalizer.CorpusNormalizer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.corpus_normalizer import CorpusNormalizer
from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace


def make_workspace(tmp_path: Path) -> RunWorkspace:
    runs = tmp_path / "runs"
    runs.mkdir()
    return RunWorkspace.new_run(runs)


def write_news_articles(ws: RunWorkspace, articles: list[dict]) -> None:
    ws.news_articles.write_text(json.dumps(articles), encoding="utf-8")


def write_vendor_blogs(ws: RunWorkspace, posts: list[dict]) -> None:
    ws.vendor_blogs_posts.write_text(json.dumps(posts), encoding="utf-8")


def long_summary(words: int = 35) -> str:
    return " ".join(["word"] * words)


CORPUS_KEYS = {"id", "source", "account_or_outlet", "posted_at", "text", "url"}


def test_normalizes_news_articles_to_corpus_schema(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(
        ws,
        [
            {
                "url": "https://example.com/a",
                "title": "Title A",
                "source": "Hacker News",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": long_summary(),
            }
        ],
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert len(corpus) == 1
    item = corpus[0]
    assert set(item) == {"id", "source", "account_or_outlet", "posted_at", "text", "url"}
    assert item["source"] == "news"
    assert item["account_or_outlet"] == "Hacker News"
    assert item["posted_at"] == "2026-05-26T10:00:00Z"
    assert item["url"] == "https://example.com/a"
    assert item["text"]
    assert item["id"]


def test_unions_news_and_vendor_blogs_into_one_corpus(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(
        ws,
        [
            {
                "url": "https://example.com/news-a",
                "title": "News A",
                "source": "Hacker News",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": long_summary(40),
            }
        ],
    )
    write_vendor_blogs(
        ws,
        [
            {
                "url": "https://claude.com/blog/post-1",
                "title": "Vendor Post 1",
                "source": "Anthropic",
                "published_at": "2026-05-25T09:00:00Z",
                "summary": long_summary(40),
            }
        ],
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert {item["source"] for item in corpus} == {"news", "vendor_blogs"}
    assert all(set(item) == CORPUS_KEYS for item in corpus)
    vendor = next(item for item in corpus if item["source"] == "vendor_blogs")
    assert vendor["account_or_outlet"] == "Anthropic"
    assert vendor["posted_at"] == "2026-05-25T09:00:00Z"
    assert vendor["url"] == "https://claude.com/blog/post-1"
    assert vendor["text"]
    assert vendor["id"]
    entries = consequential_entries(ws)
    assert len(entries) == 1 and "0" in entries[0]["message"]
    # idempotency
    CorpusNormalizer(ws, log).run()
    assert json.loads(ws.corpus.read_text(encoding="utf-8")) == corpus


def test_only_vendor_blogs_present_yields_vendor_only_corpus(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_vendor_blogs(
        ws,
        [
            {
                "url": "https://developers.openai.com/blog/p1",
                "title": "OpenAI Post",
                "source": "OpenAI Developers",
                "published_at": "2026-05-24T08:00:00Z",
                "summary": long_summary(40),
            }
        ],
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert len(corpus) == 1
    assert corpus[0]["source"] == "vendor_blogs"
    assert corpus[0]["account_or_outlet"] == "OpenAI Developers"
    assert set(corpus[0]) == CORPUS_KEYS
    entries = consequential_entries(ws)
    assert len(entries) == 1 and "0" in entries[0]["message"]
    # idempotency
    CorpusNormalizer(ws, log).run()
    assert json.loads(ws.corpus.read_text(encoding="utf-8")) == corpus


def test_drops_items_with_fewer_than_thirty_words(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(
        ws,
        [
            {
                "url": "https://example.com/short",
                "title": "Short",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": "too short to keep",
            },
            {
                "url": "https://example.com/long",
                "title": "Long",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": long_summary(40),
            },
            {
                "url": "https://example.com/exactly-29",
                "title": "Edge",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": " ".join(["w"] * 29),
            },
            {
                "url": "https://example.com/exactly-30",
                "title": "Edge",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": " ".join(["w"] * 30),
            },
        ],
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    urls = {item["url"] for item in corpus}
    assert urls == {"https://example.com/long", "https://example.com/exactly-30"}


def test_logs_dropped_count_as_consequential_info(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(
        ws,
        [
            {
                "url": "https://example.com/a",
                "title": "A",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": "tiny",
            },
            {
                "url": "https://example.com/b",
                "title": "B",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": "also tiny one",
            },
            {
                "url": "https://example.com/c",
                "title": "C",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": long_summary(40),
            },
        ],
    )

    CorpusNormalizer(ws, log).run()

    entries = [json.loads(line) for line in ws.errors.read_text(encoding="utf-8").splitlines() if line]
    consequential = [e for e in entries if e.get("kind") == "consequential"]
    assert len(consequential) == 1
    entry = consequential[0]
    assert entry["step"] == "normalize"
    assert entry["severity"] == "info"
    assert "2" in entry["message"]


def test_idempotent_when_rerun_on_same_workspace(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(
        ws,
        [
            {
                "url": "https://example.com/a",
                "title": "A",
                "source": "HN",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": long_summary(40),
            }
        ],
    )

    CorpusNormalizer(ws, log).run()
    first = ws.corpus.read_text(encoding="utf-8")
    CorpusNormalizer(ws, log).run()
    second = ws.corpus.read_text(encoding="utf-8")

    assert first == second


def test_empty_input_produces_empty_corpus(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(ws, [])

    CorpusNormalizer(ws, log).run()

    assert json.loads(ws.corpus.read_text(encoding="utf-8")) == []


def test_missing_input_file_treated_as_empty(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)

    CorpusNormalizer(ws, log).run()

    assert json.loads(ws.corpus.read_text(encoding="utf-8")) == []


def consequential_entries(ws: RunWorkspace) -> list[dict]:
    lines = ws.errors.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line and json.loads(line).get("kind") == "consequential"]


def test_both_sources_empty_yields_empty_corpus_and_zero_drop(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(ws, [])
    write_vendor_blogs(ws, [])

    items = CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert corpus == []
    entries = consequential_entries(ws)
    assert len(entries) == 1
    assert "0" in entries[0]["message"]
    # idempotency: a second run rewrites identical corpus content
    CorpusNormalizer(ws, log).run()
    assert json.loads(ws.corpus.read_text(encoding="utf-8")) == corpus


def test_all_records_filtered_out_combines_drop_count_across_sources(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_news_articles(
        ws,
        [
            {
                "url": "https://example.com/news-short",
                "title": "Short news",
                "source": "Hacker News",
                "published_at": "2026-05-26T10:00:00Z",
                "summary": "too short",
            }
        ],
    )
    write_vendor_blogs(
        ws,
        [
            {
                "url": "https://claude.com/blog/short",
                "title": "Short vendor",
                "source": "Anthropic",
                "published_at": "2026-05-25T09:00:00Z",
                "summary": "also short",
            }
        ],
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert corpus == []
    entries = consequential_entries(ws)
    assert len(entries) == 1
    assert entries[0]["step"] == "normalize"
    assert entries[0]["severity"] == "info"
    assert "2" in entries[0]["message"]
    # idempotency
    CorpusNormalizer(ws, log).run()
    assert json.loads(ws.corpus.read_text(encoding="utf-8")) == corpus
