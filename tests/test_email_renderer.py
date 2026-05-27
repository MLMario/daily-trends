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
from scripts.lib.error_log import ErrorLog
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


def test_full_path_appends_errors_and_skips_section_grouped_by_step(tmp_path: Path) -> None:
    # When the run logged failures/skips, the topic-card email carries a tail
    # Errors & Skips section, one subsection per step, after the topic content.
    ws = make_workspace(tmp_path)
    write_topics(
        ws,
        [{"topic_id": "t1", "topic_name": "A topic", "description": "d1",
          "conversation_summary": "s1", "member_ids": []}],
    )
    write_recommendations(ws, [])
    write_corpus(ws, [])
    log = ErrorLog(ws.errors)
    log.log(step="fetch", severity="warning", message="vendor_blogs slow")
    log.log(step="cluster", severity="error", message="bad clustering output")

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    assert "Errors &amp; Skips" in html
    # Both steps appear, after the topic content.
    assert "fetch" in html and "cluster" in html
    assert html.index("A topic") < html.index("Errors &amp; Skips")
    assert html.index("Errors &amp; Skips") < html.index("fetch") < html.index("cluster")


def test_light_signal_path_appends_errors_and_skips_section(tmp_path: Path) -> None:
    # The slow-day email is exactly where pipeline health matters most, so it
    # carries the same Errors & Skips tail when the run logged anything.
    ws = make_workspace(tmp_path)
    write_skipped(ws, reason="quiet day", corpus_size=2)
    write_corpus(
        ws,
        [{"id": "c1", "source": "news", "account_or_outlet": "Hacker News",
          "posted_at": "", "text": "A lone item.", "url": "https://hn.example/1"}],
    )
    log = ErrorLog(ws.errors)
    log.log(step="normalize", severity="info",
            message="dropped 3 item(s) with word_count < 30", kind="consequential")

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    assert "Errors &amp; Skips" in html
    assert "normalize" in html
    # The consequential row renders as a bullet, HTML-escaped (< → &lt;).
    assert "dropped 3 item(s) with word_count &lt; 30" in html
    # Tail position: after the corpus one-liners.
    assert html.index("A lone item.") < html.index("Errors &amp; Skips")


def test_errors_section_omitted_when_summary_is_empty(tmp_path: Path) -> None:
    # No section when nothing was logged (full path), and — critically — none
    # when the log holds only pure-info stage-timing markers (light-signal path):
    # those exist for later analysis and must never surface in the inbox.
    a = tmp_path / "a"
    a.mkdir()
    full = make_workspace(a)
    write_topics(full, [{"topic_id": "t1", "topic_name": "Quiet topic", "description": "d",
                         "conversation_summary": "s", "member_ids": []}])
    write_recommendations(full, [])
    write_corpus(full, [])
    full_html = EmailRenderer(full).render(run_id=full.run_id)
    assert "Errors &amp; Skips" not in full_html

    b = tmp_path / "b"
    b.mkdir()
    light = make_workspace(b)
    write_skipped(light, reason="quiet day", corpus_size=1)
    write_corpus(light, [{"id": "c1", "source": "news", "account_or_outlet": "HN",
                          "posted_at": "", "text": "An item.", "url": "https://hn.example/1"}])
    timing = ErrorLog(light.errors)
    timing.log(step="init_run", severity="info", message="start 2026-05-27T12:00:00Z")
    timing.log(step="render", severity="info", message="start 2026-05-27T12:05:00Z")
    light_html = EmailRenderer(light).render(run_id=light.run_id)
    assert "Errors &amp; Skips" not in light_html


def test_consequential_rows_render_under_their_own_step(tmp_path: Path) -> None:
    # Multiple steps with consequential info: each row must sit beneath its own
    # step heading, in step first-seen order — not pooled into one list.
    ws = make_workspace(tmp_path)
    write_topics(ws, [{"topic_id": "t1", "topic_name": "T", "description": "d",
                       "conversation_summary": "s", "member_ids": []}])
    write_recommendations(ws, [])
    write_corpus(ws, [])
    log = ErrorLog(ws.errors)
    log.log(step="normalize", severity="info",
            message="dropped 5 short items", kind="consequential")
    log.log(step="recommend", severity="warning", message="thin ideas")
    log.log(step="recommend", severity="info",
            message="2 topics got no ideas", kind="consequential")

    html = EmailRenderer(ws).render(run_id=ws.run_id)

    # Each consequential row nests under its step, steps in first-seen order.
    assert (
        html.index("normalize")
        < html.index("dropped 5 short items")
        < html.index("recommend")
        < html.index("2 topics got no ideas")
    )
    # recommend's counts reflect its one warning.
    assert "0 error(s), 1 warning(s)" in html


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
