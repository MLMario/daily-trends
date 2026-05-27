"""Behavior tests for scripts.lib.x_scraper.XScraper.

The pure transform (filter -> stitch -> map) is the high-value surface and is
exercised fixture-driven with no mocking: raw Bright Data post lists in, uniform
raw-schema items out. Orchestration (per-account empty -> info, failure ->
warning) is exercised with a tiny fake client and a real ErrorLog.

Raw fixtures mirror the REAL Bright Data X JSON dataset shape (confirmed against
a live @elonmusk sample), which differs from the CSV-sample shape the module was
first built against:

  * Every record carries a populated ``parent_post_details``. On an original or
    a quote it is **self-referential** (``post_id`` == the post's own ``id``) —
    it is NOT a reply marker. A genuine reply has ``post_id`` != own ``id``.
  * Self vs. reply-to-others is decided by the numeric ``profile_id`` vs the
    post's own ``user_id`` — never ``profile_name`` (which flips between handle
    ``"elonmusk"`` and display name ``"Elon Musk"`` across record types).
  * A quote carries a populated ``quoted_post`` (``post_id``/``url`` present);
    a non-quote is ``{"photos": None, "videos": None}``.
  * A repost is flagged by the boolean ``is_repost``.
  * ``parent_post_details`` has NO ``url`` field — only
    ``post_id``/``profile_id``/``profile_name``/``date_posted``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.lib.bright_data_client import SnapshotTimeout
from scripts.lib.error_log import ErrorLog
from scripts.lib.x_scraper import XScraper


@dataclass
class FakeClient:
    """A BrightDataClient stand-in: one scripted result (or failure) per profile URL."""

    results: dict[str, list[dict]] = field(default_factory=dict)
    failures: dict[str, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def discover_posts(self, *, profile_url: str, start_date: str, end_date: str) -> list[dict]:
        self.calls.append(profile_url)
        if profile_url in self.failures:
            raise self.failures[profile_url]
        return self.results.get(profile_url, [])


# Numeric account ids, as the real API assigns them (post["user_id"] and a
# self-authored parent's profile_id both carry this).
HANDLE_UID = {"karpathy": "100", "openaidevs": "300", "someone": "999"}


def raw_post(
    *,
    handle: str = "karpathy",
    post_id: str,
    text: str,
    date: str,
    reply_to: tuple[str, str] | None = None,
    quoted: bool = False,
    is_repost: bool = False,
) -> dict:
    """A Bright Data X record. Defaults describe an original top-level post.

    ``reply_to`` = ``(parent_post_id, parent_profile_id)`` makes the record a
    genuine reply (parent post_id differs from own id). A self-reply passes the
    same account's uid as the parent profile_id; a reply-to-others passes a
    different one. ``quoted`` populates ``quoted_post``; ``is_repost`` sets the
    repost flag.
    """
    uid = HANDLE_UID.get(handle, "999")
    if reply_to is None:
        # NOT a reply: parent_post_details is self-referential filler (real shape).
        parent = {
            "post_id": post_id,
            "profile_id": uid,
            "profile_name": handle.title(),  # display-name form, as the API emits here
            "date_posted": date,
        }
    else:
        parent_post_id, parent_uid = reply_to
        parent = {
            "post_id": parent_post_id,
            "profile_id": parent_uid,
            "profile_name": "whoever",
            "date_posted": "2020-01-01T00:00:00.000Z",
        }
    if quoted:
        quoted_post = {
            "post_id": "888",
            "profile_id": "ArtemisConsort",
            "profile_name": "Hunter Ash",
            "data_posted": date,  # sic: the live API misspells this key
            "url": "https://x.com/someone/status/888",
            "description": "the quoted post's text",
            "videos": None,
        }
    else:
        quoted_post = {"photos": None, "videos": None}
    return {
        "id": post_id,
        "user_posted": handle,
        "user_id": uid,
        "name": "Andrej Karpathy",
        "description": text,
        "date_posted": date,
        "url": f"https://x.com/{handle}/status/{post_id}",
        "is_repost": is_repost,
        "parent_post_details": parent,
        "quoted_post": quoted_post,
        # engagement — must never reach the output
        "replies": 12,
        "reposts": 34,
        "likes": 567,
        "views": 8900,
    }


SCHEMA_KEYS = {"url", "title", "source", "published_at", "summary"}


def test_original_top_level_post_maps_to_one_uniform_item() -> None:
    posts = [
        raw_post(
            post_id="1",
            text="transformers are all you need",
            date="2026-05-27T10:00:00.000Z",
        )
    ]

    items = XScraper.transform(posts, handle="karpathy")

    assert len(items) == 1
    item = items[0]
    assert set(item) == SCHEMA_KEYS
    assert item["url"] == "https://x.com/karpathy/status/1"
    assert item["title"] == ""
    assert item["source"] == "@karpathy"
    assert item["published_at"] == "2026-05-27T10:00:00.000Z"
    assert item["summary"] == "transformers are all you need"


def test_replies_quotes_and_reposts_are_filtered_out() -> None:
    posts = [
        raw_post(post_id="1", text="an original take on scaling laws", date="2026-05-27T09:00:00.000Z"),
        # reply to someone else's post (parent authored by a different uid) — drop
        raw_post(
            post_id="2",
            text="@someone good point",
            date="2026-05-27T09:05:00.000Z",
            reply_to=("500", HANDLE_UID["someone"]),
        ),
        # quote tweet — drop
        raw_post(post_id="3", text="adding my hot take ->", date="2026-05-27T09:10:00.000Z", quoted=True),
        # repost — drop (is_repost flag is the real signal)
        raw_post(post_id="4", text="someone else's words", date="2026-05-27T09:15:00.000Z", is_repost=True),
    ]

    items = XScraper.transform(posts, handle="karpathy")

    assert [item["url"] for item in items] == ["https://x.com/karpathy/status/1"]


def test_self_reply_thread_stitches_into_one_item_keyed_on_the_root() -> None:
    # A 3-post self-thread, fed out of chronological order, plus an unrelated original.
    uid = HANDLE_UID["karpathy"]
    posts = [
        raw_post(
            post_id="3",
            text="and so the loss converges",
            date="2026-05-27T10:10:00.000Z",
            reply_to=("2", uid),
        ),
        raw_post(
            post_id="1",
            text="a thread on training dynamics",
            date="2026-05-27T10:00:00.000Z",
        ),
        raw_post(
            post_id="2",
            text="first the gradients explode",
            date="2026-05-27T10:05:00.000Z",
            reply_to=("1", uid),
        ),
        raw_post(post_id="9", text="unrelated shower thought", date="2026-05-27T11:00:00.000Z"),
    ]

    items = XScraper.transform(posts, handle="karpathy")

    # one stitched thread + one unrelated original — continuations never standalone
    assert [item["url"] for item in items] == [
        "https://x.com/karpathy/status/1",
        "https://x.com/karpathy/status/9",
    ]
    thread = items[0]
    assert set(thread) == SCHEMA_KEYS  # engagement noise never reaches a stitched item
    assert thread["published_at"] == "2026-05-27T10:00:00.000Z"  # the root's date
    assert thread["summary"] == (
        "a thread on training dynamics\n\n"
        "first the gradients explode\n\n"
        "and so the loss converges"
    )


def test_self_reply_whose_root_is_outside_the_window_promotes_the_topmost_continuation() -> None:
    # Only the continuation is in the window; its parent ("1") was never fetched.
    # It must surface keyed on itself, not be dropped as a dangling reply.
    uid = HANDLE_UID["karpathy"]
    posts = [
        raw_post(
            post_id="2",
            text="continuing a thread whose root we didn't fetch",
            date="2026-05-27T10:05:00.000Z",
            reply_to=("1", uid),
        ),
    ]

    items = XScraper.transform(posts, handle="karpathy")

    assert [item["url"] for item in items] == ["https://x.com/karpathy/status/2"]
    assert items[0]["summary"] == "continuing a thread whose root we didn't fetch"


def test_scrape_records_an_empty_account_as_consequential_info(tmp_path) -> None:
    client = FakeClient(results={"https://x.com/karpathy": []})
    log = ErrorLog(tmp_path / "errors.jsonl")

    items = XScraper(client, log).scrape(
        ["@karpathy"], start_date="05-26-2026", end_date="05-27-2026"
    )

    assert items == []
    groups = {g.step: g for g in log.summary().groups}
    assert "x" in groups  # surfaces in Errors & Skips
    assert groups["x"].error_count == 0
    assert groups["x"].warning_count == 0
    assert any("karpathy" in note for note in groups["x"].consequential)


def test_scrape_isolates_a_per_account_failure_as_a_warning(tmp_path) -> None:
    good = [raw_post(handle="openaidevs", post_id="7", text="shipping today", date="2026-05-27T08:00:00.000Z")]
    client = FakeClient(
        results={"https://x.com/openaidevs": good},
        failures={"https://x.com/karpathy": SnapshotTimeout("never readied")},
    )
    log = ErrorLog(tmp_path / "errors.jsonl")

    items = XScraper(client, log).scrape(
        ["@karpathy", "@openaidevs"], start_date="05-26-2026", end_date="05-27-2026"
    )

    # the failing account does not abort the run — the healthy account still contributes
    assert [item["url"] for item in items] == ["https://x.com/openaidevs/status/7"]
    # one snapshot per account, even though the first failed
    assert client.calls == ["https://x.com/karpathy", "https://x.com/openaidevs"]
    groups = {g.step: g for g in log.summary().groups}
    assert groups["x"].warning_count == 1
    assert groups["x"].error_count == 0
