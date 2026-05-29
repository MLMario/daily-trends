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
