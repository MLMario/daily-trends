"""Behavior tests for the CorpusNormalizer Instagram reader.

Fixtures derived from `_tmp/slice-b-feasibility/stage3_reels_meta.raw.json`
shape — only the schema-essential fields the reader actually consults
(`url`, `user_posted`, `description`, `date_posted`, `post_id`,
`shortcode`). Transcript files follow the locked ADR-0003 schema
(`text`, optional `text_en`, `language`, `duration_sec`).

The reader walks `runs/<run_id>/instagram/<account>/` for `<post_id>.meta.json`
+ `<post_id>.transcript.json` pairs. Composed text is `transcript.text_en or
transcript.text`, optionally suffixed with `\n\n[Caption: <description>]` when
the meta description is non-empty. A Reel without a transcript is dropped at
read time with a per-item warning; the shared 30-word filter applies afterward.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.corpus_normalizer import CorpusNormalizer
from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace


def error_entries(ws: RunWorkspace) -> list[dict]:
    if not ws.errors.exists():
        return []
    return [
        json.loads(line)
        for line in ws.errors.read_text(encoding="utf-8").splitlines()
        if line
    ]


CORPUS_KEYS = {"id", "source", "account_or_outlet", "posted_at", "text", "url"}


def make_workspace(tmp_path: Path) -> RunWorkspace:
    runs = tmp_path / "runs"
    runs.mkdir()
    return RunWorkspace.new_run(runs)


def long_transcript(words: int = 35) -> str:
    return " ".join(["word"] * words)


def write_ig_reel(
    ws: RunWorkspace,
    account: str,
    *,
    post_id: str,
    shortcode: str,
    description: str | None = None,
    date_posted: str = "2026-05-21T02:52:20.000Z",
    transcript: dict | None = None,
) -> None:
    """Materialize an IG Reel's meta.json (+ transcript.json if provided).

    `transcript=None` simulates a Reel whose Whisper run never landed —
    the meta file is present, but no `.transcript.json` exists. This is the
    shape that should trigger the transcript-required-or-drop rule.
    """
    account_dir = ws.path / "instagram" / account
    account_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "url": f"https://www.instagram.com/p/{shortcode}/",
        "user_posted": account,
        "description": description,
        "date_posted": date_posted,
        "post_id": post_id,
        "shortcode": shortcode,
    }
    (account_dir / f"{post_id}.meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    if transcript is not None:
        (account_dir / f"{post_id}.transcript.json").write_text(
            json.dumps(transcript), encoding="utf-8"
        )


def test_transcript_only_reel_becomes_corpus_item(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3901640805393815120_51994227",
        shortcode="DYlaaQGqtZQ",
        description=None,
        date_posted="2026-05-21T02:52:20.000Z",
        transcript={
            "text": long_transcript(),
            "language": "en",
            "duration_sec": 174.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert len(corpus) == 1
    item = corpus[0]
    assert set(item) == CORPUS_KEYS
    assert item["source"] == "instagram"
    assert item["account_or_outlet"] == "@hellovidya"
    assert item["posted_at"] == "2026-05-21T02:52:20.000Z"
    assert item["url"] == "https://www.instagram.com/p/DYlaaQGqtZQ/"
    assert item["text"] == long_transcript()
    assert item["id"]


def test_caption_appended_as_marker_when_description_non_empty(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3905022243161873792_51994227",
        shortcode="DYxbQpbqZ2A",
        description="Harvard is capping the number of A's to 20%.",
        transcript={
            "text": long_transcript(),
            "language": "en",
            "duration_sec": 154.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert len(corpus) == 1
    assert corpus[0]["text"] == (
        long_transcript() + "\n\n[Caption: Harvard is capping the number of A's to 20%.]"
    )


def test_whitespace_only_description_does_not_append_caption_marker(tmp_path: Path) -> None:
    # The composition rule keys off `description.strip()` being non-empty —
    # a whitespace-only caption is the same as no caption.
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3905022243161873792_51994227",
        shortcode="DYxbQpbqZ2A",
        description="   \n\t  ",
        transcript={
            "text": long_transcript(),
            "language": "en",
            "duration_sec": 154.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert len(corpus) == 1
    assert corpus[0]["text"] == long_transcript()
    assert "[Caption:" not in corpus[0]["text"]


def test_transcript_absent_drops_reel_and_logs_warning(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3901640805393815120_51994227",
        shortcode="DYlaaQGqtZQ",
        description="Some caption that on its own wouldn't be enough signal.",
        transcript=None,
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert corpus == []

    warnings = [
        e for e in error_entries(ws)
        if e["severity"] == "warning" and e["step"] == "normalize"
    ]
    assert len(warnings) == 1
    assert warnings[0]["item_id"] == "3901640805393815120_51994227"
    assert warnings[0]["message"] == "skipped IG reel — no transcript"


def test_empty_transcript_text_drops_reel_with_same_warning(tmp_path: Path) -> None:
    # Transcript file exists but its `text` field is empty — same outcome as
    # missing-file: drop + warning. Whisper occasionally produces this on
    # silent or unintelligible audio.
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3905022243161873792_51994227",
        shortcode="DYxbQpbqZ2A",
        description=None,
        transcript={"text": "", "language": "en", "duration_sec": 5.0},
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert corpus == []
    warnings = [
        e for e in error_entries(ws)
        if e["severity"] == "warning" and e["step"] == "normalize"
    ]
    assert len(warnings) == 1
    assert warnings[0]["item_id"] == "3905022243161873792_51994227"
    assert warnings[0]["message"] == "skipped IG reel — no transcript"


def test_non_english_reel_uses_text_en_for_corpus_text(tmp_path: Path) -> None:
    # Two-pass Whisper output: `text` holds the native-language transcript
    # and `text_en` holds the translated pass. The clustering subagent reads
    # English only, so `text_en` is what the corpus carries.
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    spanish = "Hola amigos, hoy vamos a hablar de inteligencia artificial " * 4
    english = "Hi friends, today we are going to talk about artificial intelligence " * 4
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3909999999999999999_51994227",
        shortcode="DYesnonengl",
        description=None,
        transcript={
            "text": spanish,
            "text_en": english,
            "language": "es",
            "duration_sec": 90.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert len(corpus) == 1
    assert corpus[0]["text"] == english
    assert "Hola" not in corpus[0]["text"]


def test_non_english_reel_with_caption_appends_caption_after_text_en(tmp_path: Path) -> None:
    # `text_en` is the primary; the caption suffix rule is unchanged.
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    english = "Today we discuss the latest research in large language models. " * 5
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3910000000000000000_51994227",
        shortcode="DYesnonengC",
        description="Una reflexión sobre IA",
        transcript={
            "text": "Hoy hablamos de los últimos avances en modelos de lenguaje. " * 5,
            "text_en": english,
            "language": "es",
            "duration_sec": 90.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert len(corpus) == 1
    assert corpus[0]["text"] == f"{english}\n\n[Caption: Una reflexión sobre IA]"


def test_short_ig_text_after_composition_drops_via_shared_word_filter(tmp_path: Path) -> None:
    # The 30-word filter applies post-composition; an IG Reel with a 10-word
    # transcript and a 5-word caption still falls below the threshold and
    # drops. The drop lands in the consequential `dropped N` info summary —
    # not in a per-item warning (that's reserved for transcript-absent).
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3920000000000000001_51994227",
        shortcode="DYshorttxt",
        description="A brief hot take",
        transcript={
            "text": " ".join(["w"] * 10),
            "language": "en",
            "duration_sec": 12.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    assert corpus == []
    consequential = [
        e for e in error_entries(ws)
        if e.get("kind") == "consequential" and e["step"] == "normalize"
    ]
    assert len(consequential) == 1
    assert "1" in consequential[0]["message"]
    warnings = [e for e in error_entries(ws) if e["severity"] == "warning"]
    assert warnings == []  # short text is not the transcript-absent path


def test_short_ig_text_drop_combines_with_news_drops_in_summary(tmp_path: Path) -> None:
    # IG short-text drops and news short-summary drops are tallied together —
    # the email's `dropped N` count is a single number across all sources.
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    ws.news_articles.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.com/short-news",
                    "title": "Short",
                    "source": "Hacker News",
                    "published_at": "2026-05-26T10:00:00Z",
                    "summary": "too short to keep",
                }
            ]
        ),
        encoding="utf-8",
    )
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3920000000000000002_51994227",
        shortcode="DYshortixt",
        description=None,
        transcript={"text": "very short ig text", "language": "en", "duration_sec": 4.0},
    )

    CorpusNormalizer(ws, log).run()

    consequential = [
        e for e in error_entries(ws)
        if e.get("kind") == "consequential" and e["step"] == "normalize"
    ]
    assert len(consequential) == 1
    assert "2" in consequential[0]["message"]


def test_reader_walks_multiple_account_directories(tmp_path: Path) -> None:
    # Two creators in `runs/<id>/instagram/`: each contributes one Reel; both
    # land in the corpus with the `@<handle>` prefix derived from the
    # directory's `user_posted`, not from the directory name (kept symmetric
    # in this fixture but tests would still pin user_posted being authoritative).
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3911111111111111111_51994227",
        shortcode="DYaccountA",
        description=None,
        transcript={
            "text": long_transcript(),
            "language": "en",
            "duration_sec": 60.0,
        },
    )
    write_ig_reel(
        ws,
        "aiengineerguy",
        post_id="3922222222222222222_98765432",
        shortcode="DYaccountB",
        description="Bench results worth a look",
        transcript={
            "text": long_transcript(),
            "language": "en",
            "duration_sec": 75.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    handles = sorted(item["account_or_outlet"] for item in corpus if item["source"] == "instagram")
    assert handles == ["@aiengineerguy", "@hellovidya"]
    urls = {item["url"] for item in corpus}
    assert urls == {
        "https://www.instagram.com/p/DYaccountA/",
        "https://www.instagram.com/p/DYaccountB/",
    }


def test_news_vendor_blogs_and_instagram_coexist_in_one_corpus(tmp_path: Path) -> None:
    # End-to-end shape check: all three sources land together, each item
    # conforms to the shared 6-key schema, and the per-source `source` tag
    # disambiguates them without source-specific fields leaking.
    ws = make_workspace(tmp_path)
    log = ErrorLog(ws.errors)

    ws.news_articles.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.com/news-a",
                    "title": "News A",
                    "source": "Hacker News",
                    "published_at": "2026-05-26T10:00:00Z",
                    "summary": " ".join(["w"] * 40),
                }
            ]
        ),
        encoding="utf-8",
    )
    ws.vendor_blogs_posts.write_text(
        json.dumps(
            [
                {
                    "url": "https://claude.com/blog/p-1",
                    "title": "Vendor Post",
                    "source": "Anthropic",
                    "published_at": "2026-05-25T09:00:00Z",
                    "summary": " ".join(["w"] * 40),
                }
            ]
        ),
        encoding="utf-8",
    )
    write_ig_reel(
        ws,
        "hellovidya",
        post_id="3933333333333333333_51994227",
        shortcode="DYmixed001",
        description="Quick AI roundup",
        transcript={
            "text": long_transcript(),
            "language": "en",
            "duration_sec": 90.0,
        },
    )

    CorpusNormalizer(ws, log).run()

    corpus = json.loads(ws.corpus.read_text(encoding="utf-8"))
    by_source = {item["source"]: item for item in corpus}
    assert set(by_source) == {"news", "vendor_blogs", "instagram"}
    assert all(set(item) == CORPUS_KEYS for item in corpus)
    assert by_source["news"]["account_or_outlet"] == "Hacker News"
    assert by_source["vendor_blogs"]["account_or_outlet"] == "Anthropic"
    assert by_source["instagram"]["account_or_outlet"] == "@hellovidya"
    # Only the IG item carries the @-prefix; news/vendor outlets are bare labels.
    assert not by_source["news"]["account_or_outlet"].startswith("@")
    assert not by_source["vendor_blogs"]["account_or_outlet"].startswith("@")
    # Idempotency: re-running on the same workspace yields byte-identical corpus.
    CorpusNormalizer(ws, log).run()
    assert json.loads(ws.corpus.read_text(encoding="utf-8")) == corpus
