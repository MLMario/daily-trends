# PRD: Daily Trends Pipeline — Slice B (X posts)

## Problem Statement

Slice A delivers a working daily digest from news (Hacker News + TechCrunch AI) and vendor blogs (Anthropic + OpenAI Devs). But the sharpest, earliest AI signal — researchers and builders reacting in real time, launch hot-takes, threads breaking down a paper — lives on X, and none of it reaches my inbox. I follow a set of AI accounts there, and right now I either scroll X by hand every morning (the exact chore this pipeline exists to kill) or I miss the conversation entirely. I want the people I already trust on X folded into the same clustered, recommendation-bearing digest as everything else, without standing up a parallel pipeline or re-architecting the one that works.

## Solution

Add X as the third source feeding the existing pipeline. A new deterministic Python job (`scrape_x.py`) pulls each tracked account's recent original posts via the Bright Data X dataset (discover-by-profile mode), filters to original top-level posts, stitches multi-tweet threads into single items, and writes them in the **same uniform raw schema** news and vendor blogs already use. From there nothing new happens: `CorpusNormalizer` unions X in with one extra reader, and clustering, recommendations, the topic-card email, and `/recluster` all consume X transparently because they only ever see the normalized corpus.

X is **opt-in via `creators/accounts.json[x]`**: with no handles configured, the pipeline behaves exactly as it does today and needs no new credentials. The moment a handle is added, pre-flight begins requiring `BRIGHT_DATA_KEY`, and the X job runs concurrently with the news and vendor subagents. Volume is bounded entirely by a short lookback window (`x_lookback_days`, default 1), and the word-count floor that protects clustering from news/blog stubs becomes per-source so short-form posts survive.

This is Slice B of the eventual full pipeline (see `process_design.md`). Instagram Reels + Whisper transcription remain Slice C and are out of scope here.

## User Stories

1. As the operator, I want my tracked X accounts' recent posts folded into the same daily digest as news and vendor blogs, so that I see the whole AI conversation in one email instead of scrolling X by hand.
2. As the operator, I want to list the X accounts I follow in `creators/accounts.json` as plain handle strings, so that adding or removing a creator is a one-line config edit.
3. As the operator, I want the X scraper to derive each profile URL as `https://x.com/<handle>`, so that I never have to paste full URLs or worry about x.com-vs-twitter.com drift.
4. As the operator, I want X to be entirely opt-in — an empty or absent `accounts.json[x]` means no X fetch and no new prerequisites — so that I can run the news+vendor pipeline unchanged whenever I want.
5. As the operator, I want pre-flight to require `BRIGHT_DATA_KEY` only when X accounts are configured, so that the token is mandatory exactly when it's actually needed and never otherwise.
6. As the operator, I want pre-flight to abort fast with a clear stderr message when X accounts are configured but the token is missing, so that I'm not left debugging a mid-pipeline failure.
7. As the operator, I want only original top-level posts ingested from each account, so that replies, quote tweets, and reposts don't pollute the corpus with conversational noise and amplification.
8. As the operator, I want multi-tweet threads stitched into a single corpus item (root text plus the account's self-reply continuations, in order), so that a thread's substance survives even when its first tweet is just a hook.
9. As the operator, I want a stitched thread keyed on its root tweet's URL, so that the item is stable and links back to the start of the thread.
10. As the operator, I want each account's posts bounded by a configurable lookback window (`x_lookback_days`, default 1), so that volume and cost stay controlled on a daily-digest cadence.
11. As the operator, I want no per-account post cap — the lookback window is the only volume lever — so that the scraper logic stays simple and predictable, and I tune volume in one place.
12. As the operator, I want each account fetched as its own Bright Data snapshot, so that one account's failure or timeout can't corrupt or block another account's results.
13. As the operator, I want the X scraper to run concurrently with the news and vendor-blogs subagents during the source-fetch stage, so that adding X doesn't lengthen wall-clock time materially.
14. As the operator, I want Bright Data's raw fields mapped into the existing uniform raw schema (`{url, title, source, published_at, summary}`) inside the scraper, so that `CorpusNormalizer` gains exactly one reader and nothing else in the pipeline changes.
15. As the operator, I want the post/thread text carried in `summary`, the handle in `source`, and the post timestamp in `published_at`, so that after normalization an X item reads as `account_or_outlet = @handle`, `text = the post`, with no source-specific branching downstream.
16. As the operator, I want the word-count floor to be per-source (X low, news/vendor at 30), so that punchy short tweets survive normalization while news and blog stubs are still dropped.
17. As the operator, I want media-only, link-only, and one-word X posts dropped by the low per-source floor, so that empty-signal posts don't enter clustering as noise.
18. As the operator, I want an empty result for a tracked account (it exists but posted nothing in the window) logged as info, not error, so that a quiet account reads as normal — exactly like a vendor blog with no posts in its window.
19. As the operator, I want a per-account scrape failure or snapshot timeout logged as a warning and skipped, so that one bad account never aborts the run or blocks the others.
20. As the operator, I want all X scrape events attributed to an `x` step token in `errors.log`, so that the email's Errors & Skips section pins any X problem to the X source.
21. As the operator, I want the source-fetch stage-timing marker to cover the X job too, so that wall-clock spend including X is inspectable after the fact.
22. As the operator, I want X posts to cluster, earn recommendations, and render in topic cards with no prompt or template changes, so that the synthesis I've already tuned applies to X for free.
23. As the operator, I want an X member in a topic card to render as a link from its handle to the post URL, so that I can click straight through to the tweet.
24. As the operator, I want `/recluster` to work unchanged on runs that include X, so that I can re-tune clustering/recommendation prompts against an X-bearing corpus without re-scraping.
25. As the operator, I want the X scraper to write to `runs/<run_id>/x/posts.json` in an immutable, run-id'd directory, so that X output follows the same versioned, never-overwritten convention as every other artifact.
26. As the operator, I want the `x/` directory created as part of run initialization, so that the scraper always has a place to write even on a run with no X accounts.
27. As the operator, I want engagement metrics (likes/reposts/views) used nowhere in Slice B, so that the scraper stays simple and the corpus stays free of fields nothing reads.
28. As the operator, I want the X provider isolated behind a client module, so that swapping providers later is contained to the scraper and never touches the corpus boundary or anything downstream.
29. As the operator, I want `process_design.md` and the slice glossary to reflect that X is Slice B and Instagram is Slice C, so that the docs match the real build order.
30. As the operator, I want adding X to follow the documented "more readers in CorpusNormalizer, more keys in config" extensibility promise, so that Slice C (Instagram) lands the same way without a redesign.

## Implementation Decisions

**Scope.** Slice B adds the `x` source to the existing pipeline. No changes to clustering, recommendations, email rendering, Gmail dispatch, or `/recluster` — those operate on the normalized corpus and are source-agnostic by design. Instagram Reels + Whisper remain Slice C.

**Provider — Bright Data (see ADR 0001).** X posts are scraped via the Bright Data X dataset (`gd_lwxkxvnf1cynvib9co`), "discover by profile URL" mode, which accepts `start_date`/`end_date` (MM-DD-YYYY) per profile. This resolves the former open question on date-range listing (confirmed supported). Apify was the considered alternative (both keys are in `.env`); Bright Data was kept as the incumbent and the provider is isolated so a swap stays cheap.

**Fetch shape.** Asynchronous: trigger snapshot → poll until ready → download. **One snapshot per account** (cleaner per-account isolation; account lists are small at a 1-day window). The X job runs in the source-fetch stage **concurrently** with the news + vendor-blogs subagents, matching the existing single-tool-block concurrency pattern.

**Post selection.**
- **Original top-level posts only.** Replies (to others), quote tweets, and pure reposts are filtered out in the scraper before normalization.
- **Threads are stitched.** A chain of self-replies (each reply's parent is the same account's prior post) is concatenated — root text + continuations in order — into one corpus item, keyed on the root tweet's URL. Continuation tweets never appear as standalone items.
- **No per-account cap.** The lookback window (`x_lookback_days`, default 1) is the sole volume control.
- Engagement metrics are not used for selection and not persisted to the corpus.

**Schema mapping (inside the scraper).** Bright Data's raw fields are mapped to the uniform raw source schema `{url, title, source, published_at, summary}` so `CorpusNormalizer` needs no field-mapping changes: `source` = handle, `summary` = post/thread text, `published_at` = `date_posted`, `url` = post URL, `title` = "" (the corpus has no title field; the clustering subagent derives titles for `other_notable`). After normalization an X corpus item is `{source: "x", account_or_outlet: <handle>, text: <post>, …}`.

**Gating.** X is opt-in via `creators/accounts.json[x]` (a list of handle strings). Empty/absent ⇒ the scraper writes an empty `x/posts.json` and makes no Bright Data call. `init_run.py` requires `BRIGHT_DATA_KEY` **only** when `accounts.json[x]` is non-empty; missing token in that case ⇒ non-zero exit + stderr, aborting before any fetch.

**Word-count floor.** `CorpusNormalizer`'s single `MIN_WORDS = 30` becomes a per-source floor map (`{"news": 30, "vendor_blogs": 30, "x": 5}`, default 30) — a module constant, consistent with the static-tuning-file philosophy. Short tweets clear the X floor; news/blog stubs are still dropped; stitched threads clear it trivially.

**Modules built / modified.**

- *BrightDataClient (deep, new)* — wraps the Bright Data Dataset API for X: a `discover_posts(profile_url, start_date, end_date)` style interface encapsulating trigger → poll snapshot (interval + timeout) → download → parse. Owns the token and all HTTP. Mirrors how `GmailSender` isolates an external service. The provider seam from ADR 0001 lives here.
- *XScraper (deep, new)* — per-account orchestration plus a **pure transform**: filter to original top-level posts, stitch self-reply threads, map to the uniform raw schema. Takes a `BrightDataClient` (injectable) and an `ErrorLog`; logs empty accounts as info and per-account failures/timeouts as warnings under the `x` step; returns/writes the combined list. The filter/stitch/map transform is pure (no I/O) and is the primary test surface.
- *RunWorkspace (modified)* — add the `x_posts` typed path (`x/posts.json`) and create the `x/` directory in `new_run()`.
- *CorpusNormalizer (modified)* — `MIN_WORDS` → per-source floor map applied by item `source`; add one `(x_posts, "x")` entry to `_sources()`. No call-site or branching changes.
- *init_run.py (modified, thin)* — read `creators/accounts.json`; if `x` is non-empty, require `BRIGHT_DATA_KEY` in addition to the existing config + oauth_client checks.
- *scrape_x.py (new, thin entry)* — Bash-callable shell: read `x_lookback_days` and `accounts.json[x]`, compute the MM-DD-YYYY window, construct `BrightDataClient` + `XScraper`, write `runs/<run_id>/x/posts.json`. No logic worth isolating; exercised by dry-run.
- *run-trends/SKILL.md (modified)* — add the `scrape_x.py` job to the source-fetch concurrent block; attribute X fetch outcomes to the `x` step; the existing `source-fetch` timing marker covers it.

**Config & data additions.**
- `config.json` gains `x_lookback_days` (default `1`).
- `creators/accounts.json` populated with `{ "x": ["<handle>", …] }`.
- `BRIGHT_DATA_KEY` already present in `.env`.

**Schemas.**
- X scraper output (`x/posts.json`, before normalization): `[{url, title, source, published_at, summary}]` — the same uniform raw schema as `news/articles.json` and `vendor_blogs/posts.json`.
- Normalized corpus: unchanged — `[{id, source, account_or_outlet, posted_at, text, url}]`, with `source: "x"`.
- `errors.log`: unchanged schema; X events use step token `x`.

## Testing Decisions

**What makes a good test here.** As in Slice A, a good test asserts the external behavior of a deep module — documented inputs produce documented outputs — without coupling to internals, and survives refactors. Collaborators are exercised for real; only genuine external services (Bright Data HTTP, like the Gmail API) are mocked.

**Modules with tests.**

- *XScraper transform (new).* The high-value, I/O-free target. Fixture inputs = raw Bright Data post lists. Assertions: original top-level posts are kept; replies, quote tweets, and reposts are filtered out; a self-reply chain is stitched into one item with concatenated text in order, keyed on the root URL; output matches the uniform raw schema exactly (`source` = handle, `summary` = text, `published_at` = timestamp); an account with no qualifying posts yields an empty contribution and an info log under step `x`; a per-account failure yields a warning under step `x` and does not raise. No mocking needed for the transform.
- *BrightDataClient (new).* Mock the HTTP transport. Assertions: the discover-by-profile trigger is shaped correctly (profile URL, MM-DD-YYYY `start_date`/`end_date`, dataset id); the poll loop waits for snapshot readiness; a timeout surfaces as the documented error/skip rather than hanging; a ready snapshot downloads and parses into raw post dicts. Mirrors `GmailSender`'s external-service test.
- *CorpusNormalizer (extend `test_corpus_normalizer.py`).* New assertions: the per-source floor keeps a ~5-word X post while still dropping a sub-30-word news item in the same run; an `x/posts.json` fixture unions into the corpus with `source = "x"` and `account_or_outlet = <handle>`; idempotency and the consequential-info drop-count log continue to hold with X present.
- *RunWorkspace (extend `test_run_workspace.py`).* New assertions: `new_run()` creates the `x/` directory; `x_posts` resolves to `x/posts.json`.

**Modules without dedicated tests.** `scrape_x.py` (thin entry) and the `run-trends` skill body are exercised by the end-to-end dry-run, consistent with `init_run.py` / `normalize_corpus.py` / `send_email.py` in Slice A.

**Prior art.** `test_corpus_normalizer.py` (fixture-driven workspace + per-source writers) is the direct model for the X reader and per-source floor tests. `test_gmail_sender.py` (unit assertions on a request payload built for an external API + a mocked external call) is the model for `BrightDataClient`. `test_run_workspace.py` is the model for the path/dir extension.

**End-to-end dry-runs (manual, post-deploy).**
- Opt-out check: empty `accounts.json[x]` ⇒ no Bright Data call, no token required, pipeline behaves exactly as Slice A.
- Opt-in smoke test: add 2–3 handles, run `/run-trends`; verify `x/posts.json` populated with originals only, threads stitched, X items appear in topic cards / other-notable, draft arrives.
- Missing-token check: configure X accounts, unset `BRIGHT_DATA_KEY`; verify pre-flight aborts with a clear stderr message.
- Quiet-account check: include a handle with no posts in the window; verify an info-level note under step `x`, not an error, and the run continues.
- Failure-injection: force one account's snapshot to fail/timeout; verify a warning under step `x`, that account skipped, other accounts and the rest of the pipeline unaffected.
- Recluster cycle: `/recluster` a recent X-bearing run; verify the copied corpus (including X items) re-clusters and re-renders cleanly with no re-scrape.

## Out of Scope

- **Instagram Reels + Whisper transcription (Slice C).** Bright Data Web Scraper API + yt-dlp + faster-whisper, and `accounts.json[instagram]`.
- **Per-account post caps and engagement-based selection/ranking.** Lookback window is the only volume lever in Slice B; clustering remains no-ranking/no-scoring.
- **Persisting engagement metrics to the corpus.** Reintroducing likes/reposts/views would mean revisiting both the scraper output and the corpus schema (noted in ADR 0001).
- **Replies, quote tweets, and reposts** as corpus items. Originals only; threads stitched.
- **Fan-out/fan-in concurrent snapshotting across accounts.** Serial per-account trigger→poll→download is fine at a 1-day window; a parallel optimization stays open if latency ever bites.
- **Cross-source deduplication.** An X post and a news article about the same story remain distinct corpus items; clustering groups them thematically.
- **Cost monitoring / quota tracking on Bright Data.** Tracked when usage warrants (free tier is 5k records/month).
- **Scheduling / trigger cadence.** Slice B remains manual-trigger via `/run-trends`, like Slice A.
- **Prompt or email-template changes.** X rides the existing synthesis and render path unchanged.

## Further Notes

- `process_design.md` has been updated: Slice B/C renumbered (X = B, Instagram = C) throughout, and the Bright Data date-range listing open question moved to Resolved. `CONTEXT.md` gained the `X post`, `Thread`, and `Account` vs `Outlet` glossary entries. `docs/adr/0001-x-scraper-provider.md` records the Bright Data-over-Apify decision and its containment to the scraper.
- The architectural payoff of mapping inside the scraper: clustering, recommendations, the topic-card renderer, and `/recluster` need zero changes because they only ever see the normalized corpus. This is the "more readers, no module restructuring" promise the codebase was designed around, and Slice C (Instagram) is expected to land the same way.
- This PRD mirrors a GitHub issue labeled `ready-for-agent`. Implementation increments will be broken out as separate issues via `/to-issues`.
- Slice ordering decided in the grill-with-docs session of 2026-05-26: X before Instagram, to ship the simpler structured-API source before taking on video download + local transcription.
