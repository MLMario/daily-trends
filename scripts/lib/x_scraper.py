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


def _is_quote(quoted_post: object) -> bool:
    """True when `quoted_post` points at a quoted tweet.

    A real quote carries the quoted post's `post_id`/`url`; a non-quote is the
    skeleton `{"photos": None, "videos": None}` (no `post_id`/`url`).
    """
    return isinstance(quoted_post, dict) and bool(
        quoted_post.get("post_id") or quoted_post.get("url")
    )


def _parent_id(post: dict) -> str:
    """The post_id this post is a reply to, or "" if it is not a reply.

    The X dataset puts a populated `parent_post_details` on *every* record; on
    an original or a quote it is **self-referential** (its `post_id` equals the
    post's own `id`). A genuine reply is the case where the parent `post_id`
    differs from the post's own `id`.
    """
    ppd = post.get("parent_post_details")
    if not isinstance(ppd, dict):
        return ""
    parent_id = str(ppd.get("post_id") or "")
    return parent_id if parent_id and parent_id != str(post.get("id") or "") else ""


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

        # Keep only this account's own original, non-quote posts. A reply whose
        # parent is authored by this same account (numeric profile_id == the
        # post's own user_id) is a self-reply (a thread continuation); a reply
        # to anyone else is dropped. Nodes are keyed by the post's own `id` —
        # the only id a parent reference exposes (there is no parent url).
        nodes: dict[str, dict] = {}
        parent_of: dict[str, str] = {}
        order: list[str] = []
        for post in raw_posts:
            if post.get("is_repost") or normalize_handle(post.get("user_posted", "")) != h:
                continue  # repost / not authored by this account
            if _is_quote(post.get("quoted_post")):
                continue  # quote tweet
            own_id = str(post.get("id") or "")
            if not own_id:
                continue
            parent_id = _parent_id(post)
            if parent_id:
                ppd = post["parent_post_details"]
                if str(ppd.get("profile_id") or "") != str(post.get("user_id") or ""):
                    continue  # reply to someone else
            nodes[own_id] = post
            order.append(own_id)
            if parent_id:
                parent_of[own_id] = parent_id

        # Each self-thread collapses to one item keyed on its topmost present
        # post: walk parent links up until a parent is missing (root in window)
        # or absent (root outside window — promote the topmost continuation).
        def representative(node_id: str) -> str:
            seen = {node_id}
            while (parent := parent_of.get(node_id)) and parent in nodes and parent not in seen:
                node_id = parent
                seen.add(node_id)
            return node_id

        groups: dict[str, list[dict]] = {}
        group_order: list[str] = []
        for node_id in order:
            rep = representative(node_id)
            if rep not in groups:
                groups[rep] = []
                group_order.append(rep)
            groups[rep].append(nodes[node_id])

        items: list[dict] = []
        for rep in group_order:
            thread = sorted(groups[rep], key=lambda p: p.get("date_posted", ""))
            summary = "\n\n".join(p.get("description", "") or "" for p in thread)
            items.append(_to_item(nodes[rep], source, summary=summary))
        return items
