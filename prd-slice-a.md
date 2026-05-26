# PRD: Daily Trends Pipeline — Slice A (News + Vendor Blogs)

## Problem Statement

I want a curated, AI-focused daily trend digest delivered to my inbox, so I can read it in one sitting, identify themes worth writing about, and turn the day's signal into Substack / LinkedIn / Instagram content without spending an hour each morning crawling Hacker News, TechCrunch, the Anthropic blog, and the OpenAI developer blog by hand.

The eventual pipeline (see `process_design.md`) covers Instagram Reels, X posts, news, and vendor blogs, but building all of that at once means weeks before I see anything in my inbox. I need a working end-to-end pipeline now — one that exercises the entire control flow (config → fetch → cluster → recommend → email) on a small, tractable slice — so I can iterate on prompt quality, error reporting, and email layout before I take on the harder source integrations (Bright Data, yt-dlp, faster-whisper).

## Solution

Build slice A of the pipeline: news-search subagent + vendor-blogs subagent → corpus normalization → topic clustering → per-topic content recommendations → email delivery. This is the smallest dependency surface that fully exercises every architectural component of the eventual full pipeline (subagent spawning, run-id'd output directories, error logging, deterministic transforms, email rendering, Gmail dispatch).

Slice A runs daily, triggered manually via a Claude Code skill. Each run produces a versioned `runs/<run_id>/` directory and a topic-card email to `mariogj1987@gmail.com`. A second skill (`recluster`) lets me re-run only the synthesis steps against an existing corpus when I tune subagent prompts, without re-fetching news.

Instagram Reels, X posts, and Whisper transcription are deferred to subsequent slices. The codebase shape established in slice A absorbs them additively (more source readers in CorpusNormalizer, more lookback keys in config, no new module categories).

## User Stories

1. As the operator, I want to trigger the pipeline by typing `/run-trends` in a Claude Code session, so that I don't have to remember a multi-step manual procedure.
2. As the operator, I want each run to write to a fresh `runs/<UTC-timestamp>/` directory, so that prior runs are preserved and never overwritten.
3. As the operator, I want the run_id to be a UTC ISO timestamp with minute precision, so that runs sort lexicographically by recency and can be referenced unambiguously.
4. As the operator, I want a single `config.json` at the repo root to control all platform settings, so that I can edit lookback windows, channel lists, and the email mode without touching pipeline code.
5. As the operator, I want a news-search subagent that fetches the live Hacker News front page and TechCrunch's AI category page, so that I get "what's trending right now" without depending on third-party APIs or tokens.
6. As the operator, I want the news subagent to apply AI-relevance judgment per item, so that generic tech news (mergers, gadgets, non-AI dev tools) doesn't pollute the corpus.
7. As the operator, I want a separate vendor-blogs subagent that fetches the latest posts from `claude.com/blog` and `developers.openai.com/blog`, so that first-party model announcements are surfaced canonically without being lost in the noise of HN/TC selection.
8. As the operator, I want the vendor-blogs lookback to be configurable (default 7 days), so that sparse posters don't produce empty result files on most days.
9. As the operator, I want the news and vendor-blogs subagents to spawn concurrently, so that wall-clock time stays low.
10. As the operator, I want each subagent to return a JSON array matching the schema `[{url, title, source, published_at, summary}]`, so that the corpus normalizer can union sources without source-specific branching.
11. As the operator, I want a Python normalizer that unions news and vendor-blogs into a single `corpus.json` with schema `{id, source, account_or_outlet, posted_at, text, url}`, so that the clustering subagent receives one homogeneous input.
12. As the operator, I want the normalizer to drop records where `word_count(text) < 30`, so that empty or stub items don't contribute noise to clustering.
13. As the operator, I want the normalizer to log the dropped count as a consequential-info entry, so that I can see in the email summary how many items were filtered.
14. As the operator, I want clustering to be adaptive — the subagent picks the topic count based on natural groupings in the data, with a minimum of 2 items per topic — so that singleton "topics" aren't faked into existence on small days.
15. As the operator, I want items that don't cluster cleanly to land in an `other_notable` bucket, so that single-article signal is preserved without contaminating the topic structure.
16. As the operator, I want the trending-topics JSON to be `{topics: [...], other_notable: [...]}`, so that the email renderer can treat topics and singletons as distinct sections.
17. As the operator, I want a slow-day threshold of 4 items minimum: if normalized corpus < 4, skip clustering and recommendations entirely, render a "light signal" email branch instead, so that I never receive an email with zero topics and three Other Notable bullets that reads as a broken pipeline.
18. As the operator, I want the slow-day threshold to be configurable via `min_corpus_for_clustering` in `config.json`, so that I can tune it once I have a few weeks of real data.
19. As the operator, I want a recommendations subagent that produces, for each topic, one content idea per channel listed in `content_channels` plus a rationale, so that the output adapts if I add or drop a publishing platform.
20. As the operator, I want the initial `content_channels` to be `["substack", "linkedin", "instagram"]`, so that day 1 matches my current publishing surface.
21. As the operator, I want recommendations output schema `[{topic_id, ideas: {<channel>: idea_text, ...}, rationale}]`, so that adding channels later is an additive schema change.
22. As the operator, I want the email to render as topic cards (each topic shows description + summary + members + ideas + rationale in one block), so that I can read top-to-bottom and act on each topic without cross-referencing sections.
23. As the operator, I want a tail section for Other Notable items as one-liners, so that single-article signal is visible but doesn't dominate the layout.
24. As the operator, I want a final Errors & Skips section grouped by step with severity counts and consequential-info rows promoted, so that I can spot misbehavior at a glance without scanning the raw log.
25. As the operator, I want an `email_mode` config flag with values `"draft" | "send"`, so that I can run in draft mode while I'm tuning prompts and only flip to direct send when I trust the output.
26. As the operator, I want `email_mode` default `"draft"`, so that the first runs never deliver broken HTML into my inbox unannounced.
27. As the operator, I want the email subject to be `[daily-trends] Run <run_id>`, so that filtering and threading in Gmail is predictable.
28. As the operator, I want both `trending_topics.json` and `content_recommendations.json` attached to the email, so that I can re-process them downstream without re-running the pipeline.
29. As the operator, I want the rendered HTML archived to `runs/<run_id>/email_sent.html` regardless of mode, so that I have a local record of every email shaped artifact.
30. As the operator, I want all errors written to `runs/<run_id>/errors.log` in JSON-lines format with `{step, severity, item_id, message, timestamp, kind}`, so that programmatic summary and human review are both straightforward.
31. As the operator, I want non-fatal errors (e.g., one skipped item) to never abort the run, so that a single bad URL doesn't kill the whole pipeline.
32. As the operator, I want uncaught script errors to abort the remaining pipeline and surface the failing step to the console, so that real failures aren't silently masked as warnings.
33. As the operator, I want a `/recluster <source_run_id>` skill that copies `corpus.json` from a prior run into a new run directory, writes a `lineage.json` pointer, and re-executes only clustering + recommendations + email, so that I can iterate on prompts without re-fetching news (which would shuffle the input as HN's front page churns).
34. As the operator, I want pre-flight validation that checks `config.json` is present, `.env` exposes any required tokens, and `credentials/oauth_client.json` exists, so that the pipeline aborts fast with a clear stderr message rather than failing midway.
35. As the operator, I want a console line at the end of each run summarizing `run_id, topic count, recommendation count, error count, email outcome`, so that interactive runs leave a one-line audit trail in scrollback.
36. As the operator, I want subagent prompts kept as static files in `prompts/`, with the orchestrator appending config values inline when constructing each Agent call, so that prompt iteration is a single-file edit without templating engines.
37. As the operator, I want slice A's design to be additively extensible to later slices (IG, X, Whisper), so that adding sources later is "more readers in CorpusNormalizer + more keys in config" rather than a redesign.
38. As the operator, I want the slow-day light-signal email to indicate the corpus size and reason for skipping clustering, so that I can distinguish "quiet news day" from "pipeline misfire" at a glance.
39. As the operator, I want each run's pipeline stage timing to be available in `errors.log` (as info-level entries with timestamps), so that I can later analyze where wall-clock time is spent.
40. As the operator, I want the Gmail dispatcher to use OAuth scope `gmail.send` and persist its token to `credentials/token.json` with auto-refresh, so that the first-run consent is the only interactive step ever required.

## Implementation Decisions

**Scope.** Slice A consists of two subagents (news-search, vendor-blogs) plus deterministic transforms (normalize, render) and Gmail dispatch. Instagram Reels, X posts, and Whisper transcription are deferred to later slices. The eventual full pipeline of `process_design.md` remains the target; slice A is an additive vertical slice through the same architecture.

**Sources.**
- News: live `news.ycombinator.com/` and `techcrunch.com/category/artificial-intelligence/`. No API integration, no date-bounded queries. "What's there now" is the implicit window. No `news_lookback_days` config key.
- Vendor blogs: `claude.com/blog` and `developers.openai.com/blog`. Configurable list — adding more first-party blogs later is a `config.json` edit. Lookback window is explicit (`vendor_blogs_lookback_days`, default 7).
- AI-relevance filter is applied at the news subagent prompt level (hardcoded in `prompts/news_search_prompt.md`). Vendor blog posts are included unconditionally as first-party canonical content.

**Orchestration.** Two custom Claude Code skills:
- `run-trends` — full pipeline. Pre-flight → spawn news + vendor-blogs subagents concurrently → normalize → conditional clustering+recommendations (gated by slow-day threshold) → render + dispatch email.
- `recluster <source_run_id>` — copies `corpus.json` from a prior run into a new run, writes `lineage.json`, runs only steps 6-8. Each invocation produces a new immutable `runs/<id>/`.

Claude Code main session is the orchestrator. Subagents are spawned via the Agent tool with `subagent_type=general-purpose, model=sonnet`. Each subagent runs in a fresh context.

**Prompt-config wiring.** Prompt files in `prompts/` are static text. The orchestrator reads each prompt file at invocation time, appends relevant config values (channel list, vendor blog list, lookback) as plain prose, and passes the combined string to the Agent tool. No template substitution engine, no Python helper.

**Module breakdown.**

- *RunWorkspace (deep)* — single source of truth for run lifecycle. `new_run()` generates a UTC-minute-precision run_id and creates the directory tree. `existing_run(run_id)` resolves paths against an existing run for `/recluster`. Exposes typed paths for every file the pipeline reads or writes.
- *ErrorLog (deep)* — append-only JSON-lines writer plus a reader that produces a grouped `ErrorSummary`. Schema includes optional `kind: "consequential"` for info entries that affect downstream output (e.g., word_count drop count) so the email renderer can promote them above pure-info noise.
- *CorpusNormalizer (deep)* — accepts a RunWorkspace, reads all per-source JSON inputs, unions into the corpus schema, applies the `word_count < 30` filter, logs the dropped count. Adding IG transcripts or X posts later is an additional reader inside this module — no other module changes.
- *EmailRenderer (deep)* — accepts RunWorkspace and config, joins topics and recommendations by `topic_id`, substitutes into the HTML template. Two render paths: full (topic cards + Other Notable + Errors) and light-signal (Other Notable + Errors + corpus-size note). The branch is selected by reading whether clustering was skipped (orchestrator writes `skipped_clustering.json` flag or equivalent).
- *GmailSender (deep)* — wraps `google-api-python-client`. Encapsulates OAuth load + token refresh, multipart/mixed MIME assembly (HTML body + JSON attachments), and dispatch by mode (`drafts.create` vs `messages.send`). Returns a `SendResult` indicating outcome.
- Thin Python entry points (`init_run.py`, `normalize_corpus.py`, `send_email.py`) compose the deep modules and exist purely as Bash-callable shells for the orchestrator skills.

**Configuration.**

```json
{
  "email_to": "mariogj1987@gmail.com",
  "email_mode": "draft",
  "content_channels": ["substack", "linkedin", "instagram"],
  "vendor_blogs_lookback_days": 7,
  "vendor_blogs": [
    {"name": "Anthropic", "url": "https://claude.com/blog"},
    {"name": "OpenAI Developers", "url": "https://developers.openai.com/blog"}
  ],
  "min_corpus_for_clustering": 4
}
```

**Schemas.**

- News and vendor-blogs subagent outputs (per source, before normalization): `[{url, title, source, published_at, summary}]`.
- Normalized corpus: `[{id, source, account_or_outlet, posted_at, text, url}]`.
- Trending topics: `{topics: [{topic_id, topic_name, description, conversation_summary, member_ids}], other_notable: [{id, title, url, one_line}]}`.
- Content recommendations: `[{topic_id, ideas: {<channel>: idea_text, ...}, rationale}]`. The `ideas` map is keyed by channel name; consumers iterate over keys rather than asking for fixed fields, so adding/removing channels is non-breaking.
- Errors log line: `{step, severity, item_id?, message, timestamp, kind?}` where `severity ∈ {"error", "warning", "info"}` and `kind ∈ {"consequential"}` optional.
- Run lineage (recluster output): `{source_run_id, reused: ["corpus.json"], created_at}`.

**Slow-day branch.** Pre-clustering, the orchestrator reads the normalized corpus and compares its length to `min_corpus_for_clustering`. If below threshold: write `skipped_clustering.json` flag, skip steps 6 and 7, and the EmailRenderer takes the light-signal path. Email is still always sent (or drafted), preserving "inbox is the source of truth for pipeline status."

**Concurrency.** The orchestrator skill body spawns the two source subagents (news + vendor-blogs) in a single tool block to get parallel execution. Clustering and recommendations remain sequential because they have a strict dependency chain.

**Day-1 prerequisite.** Gmail OAuth client creation in Google Cloud Console (~5 min interactive). Yields `oauth_client.json` placed under `credentials/`. First pipeline run triggers OAuth consent flow; subsequent runs auto-refresh via persisted `token.json`.

## Testing Decisions

**What makes a good test here.** A good test asserts external behavior of a deep module — given documented inputs, the module produces documented outputs — without coupling to implementation details. Tests should survive refactors of the module's internals (e.g., switching how `CorpusNormalizer` walks the run directory) without changing. Avoid tests that mock the modules' collaborators except where the collaborator is an external service (Gmail API).

**Modules with tests.**

- *CorpusNormalizer.* Inputs: fixture directories simulating `runs/<id>/news/articles.json` and `runs/<id>/vendor_blogs/posts.json` in known shapes. Assertions: produced `corpus.json` matches expected schema; word_count filter drops the right records; consequential-info log entry is written with the expected drop count; the function is idempotent (re-running on the same workspace produces identical output). Edge cases: empty input from one source, both empty, all records filtered out.

- *EmailRenderer.* Inputs: synthetic `trending_topics.json` + `content_recommendations.json` + error summary. Assertions: full-render output contains topic cards in input order, each card contains its joined recommendation, Other Notable items render as one-liners in the tail, Errors section reflects the summary grouping. Light-signal render path is tested separately with the `skipped_clustering` flag set: assertion is no topic cards, Other Notable + Errors only, corpus-size note rendered. Schema-evolution test: extra channel in `ideas` map renders without breaking layout.

- *ErrorLog.* Inputs: a fresh log file plus a series of `log(...)` calls of mixed severity and kind. Assertions: file content is valid JSON-lines, lines preserve insertion order, `summary()` groups correctly by step, counts errors and warnings separately, includes consequential-info rows in the summary while excluding pure-info rows, returns sensible output on an empty log.

- *GmailSender.* Two tests:
  - Unit test on MIME assembly — call the multipart builder with fixed HTML + two attachments, assert the resulting MIME bytes contain a text/html part, two application/json parts with correct filenames, correct `To` and `Subject` headers. No network.
  - Integration test against the real Gmail API in draft mode — call `dispatch(mode="draft")`, assert `SendResult` indicates success, list drafts via the API to confirm the created draft is present, then delete it for cleanup. Run only when OAuth credentials are present locally; skip cleanly in CI without credentials. The `mode="send"` path is not auto-tested (would pollute the inbox).

**Modules without dedicated tests.** `RunWorkspace` is exercised implicitly by any other module test (it's the input plumbing). Skill bodies (`run-trends`, `recluster`) and thin Python entry points are exercised by an end-to-end dry-run.

**Prior art.** None — this is the first executable code in this repository. Test scaffolding (pytest layout, fixtures directory) is part of this PRD's deliverable.

**End-to-end dry-runs (manual, post-deploy verification).** Borrowed and adapted from `process_design.md` section 8:
- Minimal-config smoke test: full slice-A run against current config, verify all artifacts populated and email arrives as draft.
- Slow-day check: force `min_corpus_for_clustering = 1000` to deliberately trigger the light-signal branch, verify email renders the alternate layout.
- Failure-injection: temporarily change a vendor blog URL to a 404, verify the failure lands in `errors.log` with the right step tag and the rest of the pipeline continues.
- Recluster cycle: pick a recent successful run, invoke `/recluster <id>`, verify new run directory contains a `lineage.json` pointing at the source, `corpus.json` is byte-identical to the source, and clustering+recommendations+email re-execute cleanly.
- Run-immutability check: invoke `/run-trends` twice within a few minutes; verify both runs occupy distinct directories that don't touch each other.
- Subagent output schema check: after a successful run, validate `trending_topics.json` and `content_recommendations.json` parse and contain the documented fields.

## Out of Scope

**Deferred to later slices (still planned, but not this PRD):**
- Instagram Reels scraping (Bright Data Web Scraper Dataset API + yt-dlp download).
- Faster-whisper local transcription of Reel audio.
- X posts scraping (Bright Data X Posts Dataset API, subject to the open question on date-range listing).
- Population of `creators/accounts.json`.

**Deferred indefinitely or to operations:**
- Scheduling and trigger mechanism (Windows Task Scheduler vs. manual `claude` invocation). Slice A is manual-trigger only.
- Migration from Claude Code orchestration to a headless Python orchestrator using the Anthropic SDK. The shape of `run-trends` skill body is designed to translate mechanically, but no SDK code is written here.
- Subagent quality grading and prompt A/B testing. Prompts are tuned by reading output and editing the `.md` files.
- Cost monitoring on Bright Data (not relevant until later slices).
- Disk-space management for `runs/` directories (never automatically pruned — manual cleanup if it ever matters).
- Email template polish (visual design beyond the topic-card structure, branding, custom CSS).
- Multi-recipient delivery. Slice A is single-recipient (`mariogj1987@gmail.com`).
- Re-fetching for `/recluster` (recluster always reuses corpus; it does not offer a "re-fetch source X" mode).

## Further Notes

- The `process_design.md` document in the repo root remains the eventual-target reference; slice A is its first executable subset. After slice A ships and the IG/X work begins, `process_design.md` is updated rather than this PRD.
- The grill-me session that produced this PRD locked 13 design decisions (build order, topical filter, vendor blogs as separate subagent, configurable email mode, news selection rule, adaptive clustering, skill orchestration, configurable channels + rationale-kept, two-skill iteration loop, OAuth state, topic-card email layout, deterministic Python error summary, slow-day light-signal branch) plus two implementation-detail recommendations (concurrent source subagents, static prompts + inline config). All decisions reflect a stated preference for minimum technical complexity.
- The README's "scraping content from creators plus posts from X and Instagram" framing still describes the full pipeline. Slice A intentionally narrows that to the news + vendor-blog vertical to ship a working loop before fighting Bright Data, yt-dlp, and Whisper.
- Open questions explicitly preserved from `process_design.md` for later slices: Bright Data X Dataset API account+date listing capability, faster-whisper CPU vs. GPU path, Bright Data cost monitoring at scale. None block slice A.
