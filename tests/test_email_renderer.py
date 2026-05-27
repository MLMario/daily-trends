"""Behavior tests for scripts.lib.email_renderer.EmailRenderer (topic-card path).

The renderer joins trending_topics.json + content_recommendations.json by
topic_id, resolves each topic's member_ids against corpus.json for linked
sources, and renders other_notable as a one-liner tail. Tests write synthetic
fixtures into a real RunWorkspace and assert on the returned HTML.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.email_renderer import EmailRenderer
from scripts.lib.run_workspace import RunWorkspace


def make_workspace(tmp_path: Path) -> RunWorkspace:
    runs = tmp_path / "runs"
    runs.mkdir()
    return RunWorkspace.new_run(runs)


def write_topics(ws: RunWorkspace, topics: list[dict], other_notable: list[dict] | None = None) -> None:
    payload = {"topics": topics, "other_notable": other_notable or []}
    ws.trending_topics.write_text(json.dumps(payload), encoding="utf-8")


def write_recommendations(ws: RunWorkspace, recommendations: list[dict]) -> None:
    ws.content_recommendations.write_text(json.dumps(recommendations), encoding="utf-8")


def write_corpus(ws: RunWorkspace, items: list[dict]) -> None:
    ws.corpus.write_text(json.dumps(items), encoding="utf-8")


def write_skipped(ws: RunWorkspace, *, reason: str, corpus_size: int) -> None:
    ws.skipped_clustering.write_text(
        json.dumps({"reason": reason, "corpus_size": corpus_size}), encoding="utf-8"
    )


def test_renders_a_topic_card_with_name_description_and_summary(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_topics(
        ws,
        [
            {
                "topic_id": "t1",
                "topic_name": "Agentic coding tools",
                "description": "Tools that write code autonomously.",
                "conversation_summary": "Builders are debating reliability.",
                "member_ids": [],
            }
        ],
    )
    write_recommendations(ws, [])
    write_corpus(ws, [])

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    assert "Agentic coding tools" in html
    assert "Tools that write code autonomously." in html
    assert "Builders are debating reliability." in html


def test_cards_render_in_input_order(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_topics(
        ws,
        [
            {"topic_id": "t1", "topic_name": "First topic", "description": "d1",
             "conversation_summary": "s1", "member_ids": []},
            {"topic_id": "t2", "topic_name": "Second topic", "description": "d2",
             "conversation_summary": "s2", "member_ids": []},
            {"topic_id": "t3", "topic_name": "Third topic", "description": "d3",
             "conversation_summary": "s3", "member_ids": []},
        ],
    )
    write_recommendations(ws, [])
    write_corpus(ws, [])

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    assert html.index("First topic") < html.index("Second topic") < html.index("Third topic")


def test_each_card_joins_its_recommendation_by_topic_id(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_topics(
        ws,
        [
            {"topic_id": "t1", "topic_name": "Topic Alpha", "description": "d1",
             "conversation_summary": "s1", "member_ids": []},
            {"topic_id": "t2", "topic_name": "Topic Beta", "description": "d2",
             "conversation_summary": "s2", "member_ids": []},
        ],
    )
    write_recommendations(
        ws,
        [
            {
                "topic_id": "t2",
                "ideas": {"substack": "Beta substack idea", "linkedin": "Beta linkedin idea"},
                "rationale": "Beta is rising fast.",
            },
            {
                "topic_id": "t1",
                "ideas": {"substack": "Alpha substack idea", "linkedin": "Alpha linkedin idea"},
                "rationale": "Alpha has staying power.",
            },
        ],
    )
    write_corpus(ws, [])

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    # Ideas iterate over the map keys (channel labels appear), not fixed fields.
    assert "substack" in html and "linkedin" in html
    assert "Alpha substack idea" in html and "Alpha linkedin idea" in html
    assert "Beta substack idea" in html

    # Each recommendation joins to its own card despite reversed recs order.
    assert html.index("Topic Alpha") < html.index("Alpha substack idea") < html.index("Topic Beta")
    assert html.index("Topic Alpha") < html.index("Alpha has staying power.") < html.index("Topic Beta")
    assert html.index("Topic Beta") < html.index("Beta substack idea")
    assert html.index("Topic Beta") < html.index("Beta is rising fast.")


def test_member_ids_resolve_to_linked_corpus_sources(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_topics(
        ws,
        [
            {
                "topic_id": "t1",
                "topic_name": "Topic with members",
                "description": "d1",
                "conversation_summary": "s1",
                "member_ids": ["id-hn", "id-tc", "id-missing"],
            }
        ],
    )
    write_recommendations(ws, [])
    write_corpus(
        ws,
        [
            {"id": "id-hn", "source": "news", "account_or_outlet": "Hacker News",
             "posted_at": "", "text": "t", "url": "https://news.example/item"},
            {"id": "id-tc", "source": "news", "account_or_outlet": "TechCrunch",
             "posted_at": "", "text": "t", "url": "https://tc.example/post"},
        ],
    )

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    # Resolved members render as links: visible label + href.
    assert 'href="https://news.example/item"' in html
    assert "Hacker News" in html
    assert 'href="https://tc.example/post"' in html
    assert "TechCrunch" in html
    # An id absent from the corpus is skipped, not rendered raw.
    assert "id-missing" not in html


def test_other_notable_renders_as_one_liner_tail(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_topics(
        ws,
        [
            {"topic_id": "t1", "topic_name": "The one topic", "description": "d1",
             "conversation_summary": "s1", "member_ids": []},
        ],
        other_notable=[
            {"id": "n1", "title": "Lone article one",
             "url": "https://ex.example/one", "one_line": "A single notable thing."},
            {"id": "n2", "title": "Lone article two",
             "url": "https://ex.example/two", "one_line": "Another notable thing."},
        ],
    )
    write_recommendations(ws, [])
    write_corpus(ws, [])

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    # Each notable item renders its title (linked) and one-liner.
    assert "Lone article one" in html
    assert 'href="https://ex.example/one"' in html
    assert "A single notable thing." in html
    assert "Another notable thing." in html

    # The tail sits after the topic cards, in input order.
    assert html.index("The one topic") < html.index("Lone article one")
    assert html.index("Lone article one") < html.index("Lone article two")


def test_light_signal_path_renders_without_synthesis_files(tmp_path: Path) -> None:
    # On a slow day, clustering/recommendations never run, so neither
    # trending_topics.json nor content_recommendations.json exists. The presence
    # of skipped_clustering.json must switch the renderer to the light-signal
    # path, which reads corpus directly and emits no topic cards.
    ws = make_workspace(tmp_path)
    write_skipped(ws, reason="corpus below clustering threshold", corpus_size=2)
    write_corpus(
        ws,
        [
            {"id": "c1", "source": "news", "account_or_outlet": "TechCrunch",
             "posted_at": "", "text": "A lone AI item.", "url": "https://tc.example/a"},
        ],
    )

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    # Renders despite the synthesis files being absent (full path would crash).
    assert ws.run_id in html
    # No topic-card section wrapper from the full path.
    assert "margin-bottom:2em" not in html


def test_light_signal_renders_corpus_size_note_explaining_the_skip(tmp_path: Path) -> None:
    # The light-signal email must distinguish "quiet news day" from "pipeline
    # misfire" — it states why clustering was skipped and the corpus size.
    ws = make_workspace(tmp_path)
    write_skipped(ws, reason="corpus below clustering threshold", corpus_size=3)
    write_corpus(
        ws,
        [
            {"id": "c1", "source": "news", "account_or_outlet": "Hacker News",
             "posted_at": "", "text": "Item one.", "url": "https://hn.example/1"},
        ],
    )

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    assert "corpus below clustering threshold" in html
    assert "3" in html


def test_light_signal_renders_corpus_items_as_one_liners(tmp_path: Path) -> None:
    # With clustering skipped, the corpus itself is the Other Notable tail:
    # each item renders as a linked outlet label followed by its text, in
    # corpus order.
    ws = make_workspace(tmp_path)
    write_skipped(ws, reason="quiet day", corpus_size=3)
    write_corpus(
        ws,
        [
            {"id": "c1", "source": "news", "account_or_outlet": "Hacker News",
             "posted_at": "", "text": "First quiet-day item.", "url": "https://hn.example/1"},
            {"id": "c2", "source": "vendor_blogs", "account_or_outlet": "Anthropic",
             "posted_at": "", "text": "Second quiet-day item.", "url": "https://claude.example/2"},
            {"id": "c3", "source": "news", "account_or_outlet": "TechCrunch",
             "posted_at": "", "text": "Third quiet-day item.", "url": "https://tc.example/3"},
        ],
    )

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    # Each item: outlet name linked to its url, followed by its text.
    assert 'href="https://hn.example/1"' in html
    assert "Hacker News" in html
    assert "First quiet-day item." in html
    assert 'href="https://claude.example/2"' in html
    assert "Anthropic" in html
    assert "Second quiet-day item." in html

    # Rendered in corpus order.
    assert html.index("Hacker News") < html.index("Anthropic") < html.index("TechCrunch")


def test_unexpected_extra_channel_in_ideas_renders_without_code_changes(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    write_topics(
        ws,
        [
            {"topic_id": "t1", "topic_name": "Evolving topic", "description": "d1",
             "conversation_summary": "s1", "member_ids": []},
        ],
        other_notable=[
            {"id": "n1", "title": "Tail item", "url": "https://ex.example/x",
             "one_line": "Still renders."},
        ],
    )
    write_recommendations(
        ws,
        [
            {
                "topic_id": "t1",
                "ideas": {
                    "substack": "sub idea",
                    "linkedin": "li idea",
                    "instagram": "ig idea",
                    "tiktok": "tiktok idea",  # channel not in the original config
                },
                "rationale": "r1",
            }
        ],
    )
    write_corpus(ws, [])

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    # All four channels render, including the unexpected one.
    assert "tiktok" in html and "tiktok idea" in html
    for idea in ("sub idea", "li idea", "ig idea", "tiktok idea"):
        assert idea in html
    # Layout intact: the Other Notable tail still follows the card.
    assert html.index("Evolving topic") < html.index("tiktok idea") < html.index("Tail item")
