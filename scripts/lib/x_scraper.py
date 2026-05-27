"""Per-account X scraping: fetch one snapshot per account, then a pure transform.

`transform` is the high-value, I/O-free core: it filters a Bright Data post list
to **original top-level posts only** (dropping replies-to-others, quote tweets,
and reposts), **stitches self-reply threads** (root + the account's own
continuations, in order) into one item keyed on the root tweet's URL, and maps
each surviving post to the uniform raw schema (`{url, title, source,
published_at, summary}`) news and vendor blogs already use. Engagement metrics
are used nowhere and never reach the output.

`scrape` is the thin orchestration shell around it: one Bright Data snapshot per
account so one account's failure can't block another, logging an empty account
as info and a per-account failure/timeout as a warning under the `x` step —
never raising.
"""

from __future__ import annotations

from scripts.lib.bright_data_client import BrightDataClient, BrightDataError
from scripts.lib.error_log import ErrorLog


def normalize_handle(handle: str) -> str:
    """`karpathy` or `@karpathy` -> the bare lowercase handle (no @)."""
    return handle.lstrip("@").strip()


def profile_url(handle: str) -> str:
    """The X profile URL for a handle — never twitter.com, never with an @."""
    return f"https://x.com/{normalize_handle(handle)}"


def _ref_populated(ref: object) -> bool:
    """True when a parent/quote reference object actually points at a post."""
    return isinstance(ref, dict) and bool(ref.get("post_id") or ref.get("url"))


def _handle_from_url(url: str) -> str:
    """Bare lowercase handle from an x.com post URL (`/<handle>/status/<id>`)."""
    parts = [p for p in (url or "").split("/") if p]
    for i, part in enumerate(parts):
        if part in ("x.com", "twitter.com") and i + 1 < len(parts):
            return parts[i + 1].lower()
    return ""


def _to_item(post: dict, source: str, *, summary: str | None = None) -> dict:
    return {
        "url": post["url"],
        "title": "",
        "source": source,
        "published_at": post.get("date_posted", ""),
        "summary": summary if summary is not None else (post.get("description", "") or ""),
    }


class XScraper:
    def __init__(self, client: BrightDataClient, error_log: ErrorLog) -> None:
        self._client = client
        self._log = error_log

    def scrape(
        self, handles: list[str], *, start_date: str, end_date: str
    ) -> list[dict]:
        """Fetch + transform one snapshot per account into uniform raw items.

        One snapshot per handle so one account's failure or empty result can't
        block another: a failed/timed-out snapshot is logged as a warning and an
        empty account as consequential info. Either way `scrape` never raises.
        """
        items: list[dict] = []
        for handle in handles:
            try:
                raw = self._client.discover_posts(
                    profile_url=profile_url(handle),
                    start_date=start_date,
                    end_date=end_date,
                )
            except BrightDataError as exc:
                self._log.log(
                    step="x",
                    severity="warning",
                    message=f"@{normalize_handle(handle)} fetch failed: {exc}",
                )
                continue
            contribution = self.transform(raw, handle=handle)
            if not contribution:
                self._log.log(
                    step="x",
                    severity="info",
                    message=f"@{normalize_handle(handle)} produced no posts in the lookback window",
                    kind="consequential",
                )
                continue
            items.extend(contribution)
        return items

    @staticmethod
    def transform(raw_posts: list[dict], *, handle: str) -> list[dict]:
        h = normalize_handle(handle)
        source = "@" + h

        # Keep only this account's own non-quote posts. A populated parent that
        # belongs to this same handle is a self-reply (a thread continuation);
        # a parent belonging to anyone else is a reply-to-others and is dropped.
        nodes: dict[str, dict] = {}
        parent_of: dict[str, str] = {}
        order: list[str] = []
        for post in raw_posts:
            if normalize_handle(post.get("user_posted", "")) != h:
                continue  # repost / not authored by this account
            if _ref_populated(post.get("quoted_post")):
                continue  # quote tweet
            parent_url = ""
            if _ref_populated(post.get("parent_post_details")):
                parent_url = post["parent_post_details"].get("url", "")
                if _handle_from_url(parent_url) != h:
                    continue  # reply to someone else
            url = post["url"]
            nodes[url] = post
            order.append(url)
            if parent_url:
                parent_of[url] = parent_url

        # Each self-thread collapses to one item keyed on its topmost present
        # post: walk parent links up until a parent is missing (root in window)
        # or absent (root outside window — promote the topmost continuation).
        def representative(url: str) -> str:
            seen = {url}
            while (parent := parent_of.get(url)) and parent in nodes and parent not in seen:
                url = parent
                seen.add(url)
            return url

        groups: dict[str, list[dict]] = {}
        group_order: list[str] = []
        for url in order:
            rep = representative(url)
            if rep not in groups:
                groups[rep] = []
                group_order.append(rep)
            groups[rep].append(nodes[url])

        items: list[dict] = []
        for rep in group_order:
            thread = sorted(groups[rep], key=lambda p: p.get("date_posted", ""))
            summary = "\n\n".join(p.get("description", "") or "" for p in thread)
            items.append(_to_item(nodes[rep], source, summary=summary))
        return items
