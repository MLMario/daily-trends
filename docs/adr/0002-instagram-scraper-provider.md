# ADR 0002 — Instagram Reels scraping pathway

**Status:** accepted (2026-05-28). Bright Data Web Scraper Dataset API (`gd_lyclm20il4r5helnj`, `discover_by=url`) + yt-dlp confirmed working end-to-end against `@hellovidya` with a 7-day lookback. Slice B proceeds as designed, with one small correction noted under "API shape" below.

## Decision

Slice B (Instagram Reels) builds on the design's chosen pathway: **Bright Data Web Scraper Dataset API** for Reel discovery + metadata, **yt-dlp** for `.mp4` download, **faster-whisper** for transcription (untested in this ADR — separate concern, no provider risk). No design change required beyond removing one stale field reference (`post_type`) from the awareness-check column in `process_design.md`.

## Context

`process_design.md` commits Slice B to Bright Data + yt-dlp. Two assumptions were load-bearing and untested before this ADR:

1. Bright Data's Instagram Reels dataset (discover-by-profile) returns enough metadata for a real curated AI account (`@hellovidya`) inside a 7-day lookback window.
2. yt-dlp can resolve the resulting Reel URL into a downloadable `.mp4` on Windows without an authenticated Instagram session.

ADR-0001 had falsified the analogous assumption for X across three providers, so we ran the same shape of investigation for Instagram before writing production code.

## Investigation (2026-05-28)

Single-provider feasibility test against `@hellovidya`. Code under `_tmp/slice-b-feasibility/` (gitignored, not committed). Snapshot ID `sd_mppo1vtr2a3uayfzw4`.

### API shape — confirmed by probe

- **Dataset ID:** `gd_lyclm20il4r5helnj` (instagram_reels), sourced from `brightdata/cli` `src/commands/dataset.ts` `DATASET_IDS` map.
- **Trigger:** `POST https://api.brightdata.com/datasets/v3/trigger?dataset_id=gd_lyclm20il4r5helnj&type=discover_new&discover_by=url&include_errors=true`
- **Progress poll:** `GET https://api.brightdata.com/datasets/v3/progress/{snapshot_id}`
- **Snapshot fetch:** `GET https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}?format=json`
- **Body:** `[{"url": "<profile_url>", "num_of_posts": N, "start_date": "MM-DD-YYYY", "end_date": "MM-DD-YYYY"}]`
- **Validation findings (corrections to `process_design.md`):**
  - `post_type` field is **rejected** by the reels dataset — `"This input should not contain a post_type field"`. The dataset is reels-only by definition. The awareness-check column in §4 of `process_design.md` ("API uses `post_type=reel`") should be updated when Slice B documentation lands.
  - `discover_by` accepts only `url` and `url_all_reels`. `profile_url` (which we initially tried as a more natural name) returns `"Incorrect discovery collector id"`.
  - Date format is **MM-DD-YYYY** (matches the X dataset's format from ADR-0001).

### Stage outcomes

| Stage | Outcome | Evidence |
|---|---|---|
| 1. Trigger snapshot | ✅ HTTP 200, returned `snapshot_id=sd_mppo1vtr2a3uayfzw4` | After dropping `post_type` from the body. Earlier variants returned HTTP 400 with self-explanatory validation messages. |
| 2. Poll until ready | ✅ Status `ready` at t+60.6s wall-clock (1 poll: `running` at t+0, `running` at t+30, `ready` at t+60). Server-side `collection_duration=76709ms`. `records=5`, `errors=0`. | `stage2_progress_transitions.json` |
| 3. Fetch metadata | ✅ 5 records, 42606 bytes JSON. Schema is rich (31 fields) and **covers everything the design needs and more** — see "Metadata schema" below. | `stage3_reels_meta.raw.json` |
| 4. yt-dlp download | ✅ Newest Reel (`3906868330239713824_51994227`, posted 2026-05-28T07:58:56Z) downloaded **on the first try** via the canonical Reel URL (`https://www.instagram.com/p/<shortcode>/`). No login wall, no cookies needed, no fallback to the CDN `video_url` required. 34.5 MB `.mp4`, 171.8s playback length. | `_tmp/slice-b-feasibility/3906868330239713824_51994227.mp4` |

### Metadata schema (vs. design schema)

Bright Data returns these 31 fields per record: `post_id, url, shortcode, video_url, audio_url, thumbnail, date_posted, timestamp, length, description, hashtags, tagged_users, views, likes, num_comments, video_play_count, user_posted, is_verified, followers, following, posts_count, top_comments, is_paid_partnership, partnership_details, coauthor_producers, product_type, profile_image_link, content_id, discovery_input, input`.

Mapping to the Slice B design (`process_design.md` step 1 output schema `{text, text_en?, language, duration_sec}` plus the unified corpus schema `{id, source, account_or_outlet, posted_at, text, url}`):

| Corpus field | Bright Data source field | Notes |
|---|---|---|
| `id` | `post_id` | The shortcode (`shortcode`) is also stable; `post_id` is Bright Data's primary key. |
| `source` | constant `"instagram"` | Set by `CorpusNormalizer`'s IG reader. |
| `account_or_outlet` | `user_posted` | E.g. `"hellovidya"`. |
| `posted_at` | `date_posted` | ISO 8601 UTC, e.g. `"2026-05-28T07:58:56.000Z"`. |
| `text` | `description` + (later) transcript | Slice B step 2 will append the whisper transcript before normalization. |
| `url` | `url` | Canonical `instagram.com/p/<shortcode>/` form. |
| (per-Reel artifact) | `video_url` | CDN URL — keep as fallback in `<post_id>.meta.json` in case yt-dlp's URL path ever breaks. |

### Hellovidya 7-day window contents

5 Reels found in the 7d window (2026-05-21 → 2026-05-28). All AI-domain content from the captions / titles visible in `description`:

```
3906868330239713824   2026-05-28T07:58Z   172s   1364 views   (newest — yt-dlp downloaded this)
3905022243161873792   2026-05-25T18:51Z   155s   2361 views
3904359948400385887   2026-05-24T20:55Z   158s   2266 views
3902515601673503126   2026-05-22T07:50Z   163s   5955 views
3901640805393815120   2026-05-21T02:52Z   174s   4542 views   (oldest — at the lookback edge)
```

5 records satisfies the operator's "4-5 reels minimum" success criterion. The window is a normal cadence for this creator (~daily).

## Consequences

Slice B build can begin. Concrete next steps (mirror Slice A's tracer-bullet slicing):

- **B.1 — CorpusNormalizer extension.** Add an `instagram` reader that ingests `runs/<run_id>/instagram/<account>/*.meta.json` (+ later, transcripts) into the unified corpus schema. Test-first with fixture metadata derived from `stage3_reels_meta.raw.json`. Mirrors the X-investigation `B.1` pattern that landed cleanly even though the X scraper itself failed.
- **B.2 — Config + opt-in plumbing.** Add `instagram_lookback_days` to `config.json` (default 7, matching this test), `instagram_min_word_count` if needed, populate `creators/accounts.json[instagram]` with `["hellovidya"]` as the seed creator. Wire `init_run.py` to gate the `instagram/` directory creation on `instagram` list non-empty (same pattern the rewound X opt-in used).
- **B.3 — Bright Data client + scrape_instagram.py + yt-dlp download.** `scripts/lib/bright_data.py` (POST trigger → poll → GET snapshot, with `discover_by=url` mode), `scripts/scrape_instagram.py` (per-account orchestrator: trigger, poll, write `<account>/<post_id>.meta.json`, yt-dlp `<post_id>.mp4`). All non-fatal failures logged via `ErrorLog` under step `instagram`, never aborting the run. Pattern matches Slice A's `news_search` / `vendor_blogs` subagents but in Python (deterministic) rather than via an Agent tool.
- **B.4 — faster-whisper transcription step.** `scripts/transcribe_reels.py` invoked per `.mp4`, writes `<post_id>.transcript.json` with `{text, text_en?, language, duration_sec}`. Cross-cuts hardware open question — covered separately in `process_design.md` §9 "Whisper hardware path".
- **B.5 — run-trends skill wiring.** Add Instagram as a parallel source in the source-fetch concurrent block; gate on `creators/accounts.json[instagram]` non-empty so the slice cleanly no-ops until populated.
- **Doc fix.** Update `process_design.md` step 1 awareness-check column to drop the `post_type=reel` line, replacing with "Discover-by-profile via `discover_by=url`; the reels-only dataset rejects `post_type`. See ADR-0002."

`BRIGHT_DATA_KEY` in `.env` is already wired from the X investigation; no credential setup needed. `yt-dlp` added to dev-dependencies during this investigation; will move to runtime dependencies in B.3.

## When this ADR would be re-evaluated

- If Bright Data's snapshot latency or success rate degrades on smaller AI-creator accounts (the X failure mode), revisit the provider choice. Current latency baseline: ~1 minute for 5 records on a 7d window.
- If Instagram changes its public-Reel page enough that yt-dlp can no longer fetch the `.mp4` without cookies, revisit yt-dlp config (cookies-jar) or fall back to the CDN `video_url` Bright Data already returns.
- If the curated creator list grows past Bright Data's free-tier cap (~5,000 requests/month), the cost-monitoring open question in `process_design.md` §9 becomes load-bearing.

## Considered alternatives

- **Apify Instagram actor** — not tested in this ADR. ADR-0001 found Apify Free is paywalled in practice; defaulting to Bright Data on the strength of the working smoke test rather than dual-testing.
- **Self-hosted Playwright with Instagram cookies** — engineering-heavy. Worth revisiting only if the canonical Reel URL path breaks for yt-dlp later.
- **yt-dlp standalone (skip Bright Data)** — falsified by design: yt-dlp can download one Reel given a URL but cannot enumerate "the last 7 days of Reels from a creator." Both layers are needed.
