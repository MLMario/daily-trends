---
name: run-trends
description: Run the daily-trends pipeline end-to-end against today's news and deliver a Gmail draft. Use when the user says "/run-trends", "run daily trends", "send today's trends digest", or asks to trigger the trends pipeline.
---

# run-trends

Orchestrate the pipeline: pre-flight → news + vendor-blogs subagents (parallel) → normalize → slow-day gate → cluster → recommend → render + dispatch the email. On a slow day (corpus below threshold), the gate skips clustering + recommendations and the email renders an alternate light-signal layout.

## Stage-boundary timing

Append one pure-info entry recording the stage boundary at the start of each numbered step below — except `init_run`, whose marker lands immediately *after* step 1 creates the run dir (you cannot write to `errors.log` before the dir exists). The `ErrorLog` schema auto-stamps each line with a UTC `timestamp`, so wall-clock spend per stage becomes inspectable in `errors.log` later. These are **pure info** (no `kind`), so they never appear in the email's Errors & Skips section — they exist only for after-the-fact analysis.

Use these step tokens, one marker per stage: `init_run`, `source-fetch`, `transcribe`, `normalize`, `slow-day`, `cluster`, `recommend`, `render`. (The fetch stage runs two sources in parallel — three when IG is enabled — so its *failures* are attributed per-source under `news` / `vendor_blogs` / `scrape_instagram` in step 3, but the single timing marker for the whole stage uses `source-fetch`. The `transcribe` marker fires at the start of Phase 2 when IG is enabled; per-Reel Whisper failures attribute under `transcribe_reels` inside the script itself.) For example, before fetching:

```
uv run python -c "from pathlib import Path; from scripts.lib.error_log import ErrorLog; ErrorLog(Path('runs/<run_id>/errors.log')).log(step='source-fetch', severity='info', message='stage start: source-fetch')"
```

Skip the `transcribe` marker when `creators/accounts.json[instagram]` is empty (Phase 2 doesn't run). Skip the marker for any stage the slow-day gate skips (cluster, recommend).

## Steps

1. **Pre-flight + new run.** Bash:

   ```
   uv run python -m scripts.init_run
   ```

   Capture the printed `run_id` (single line on stdout). On non-zero exit, surface the stderr message and abort.

2. **Fetch sources concurrently.** Read `prompts/news_search_prompt.md` and `prompts/vendor_blogs_prompt.md`, and read `vendor_blogs` + `vendor_blogs_lookback_days` from `config.json`. Also read `creators/accounts.json` — when `accounts.json[instagram]` is non-empty, this stage fans out **three** calls; when empty, **two** (today's Slice A shape exactly).

   - **News prompt:** append two lines — `Run ID: <run_id>` and `Output path: runs/<run_id>/news/articles.json`.
   - **Vendor-blogs prompt:** append the configured blogs and lookback window as plain prose, then the run lines. For example:

     ```
     Lookback window: 7 days.
     Blogs to fetch:
     - Anthropic — https://claude.com/blog
     - OpenAI Developers — https://developers.openai.com/blog
     Run ID: <run_id>
     Output path: runs/<run_id>/vendor_blogs/posts.json
     ```

   - **Instagram (conditional — only when `accounts.json[instagram]` is non-empty):** issue one Bash call alongside the two subagent calls:

     ```
     uv run python -m scripts.scrape_instagram <run_id>
     ```

     The script reads `creators/accounts.json[instagram]` + `config.instagram_lookback_days` + `config.instagram_num_of_posts` itself, fires one combined Bright Data snapshot, demultiplexes per creator, and shells out to yt-dlp for each `.mp4`. Per-Reel failures land in `errors.log` under `step=scrape_instagram`; the helper exits 0 on partial failure. `init_run` already created `runs/<run_id>/instagram/` because `enable_instagram` was derived from the same `accounts.json`, so the script writes into an existing tree.

   Issue **all** calls (two subagent calls plus the optional Bash) in a **single tool block** so they run in parallel. The two subagent calls use `subagent_type=general-purpose`, `model=sonnet`, fresh context, WebFetch available.

3. **Record source-fetch outcomes (non-fatal).** After all concurrent calls return, inspect each output. Attribute each event to its **source-specific step** — `news` for the news subagent, `vendor_blogs` for the vendor-blogs subagent, `scrape_instagram` for the IG Bash call — so the email's Errors & Skips section pins a failure to the source that caused it. None of these abort the run:

   - A subagent's output file is missing or unparseable → log a `warning` under that source's step (`news` or `vendor_blogs`) and continue.
   - `runs/<run_id>/vendor_blogs/posts.json` is an empty array → log an **`info`**-level note (step `vendor_blogs`) that no vendor-blog posts fell in the lookback window. This is normal, **not an error**.
   - When IG ran, walk `runs/<run_id>/instagram/<account>/` for each creator in `accounts.json[instagram]`:
     - Per-creator directory missing → log a `warning` (step `scrape_instagram`) and continue.
     - Directory present but contains no `.meta.json` files → log an **`info`**-level note (step `scrape_instagram`) that no Reels fell in the lookback window. Normal, **not an error**.
   - Each subagent also logs its own per-source fetch failures (e.g. a blog URL returning 404) under the same step token, and `scrape_instagram` logs per-Reel Bright Data / yt-dlp failures itself — see the prompts and the script. Those entries are already in `errors.log` by the time you inspect the outputs; do not duplicate them.

   Append events with the `ErrorLog` helper so each line matches the JSON-lines schema, e.g.:

   ```
   uv run python -c "from pathlib import Path; from scripts.lib.error_log import ErrorLog; ErrorLog(Path('runs/<run_id>/errors.log')).log(step='vendor_blogs', severity='info', message='no posts in the lookback window')"
   ```

4. **Normalize.** Bash:

   ```
   uv run python -m scripts.normalize_corpus <run_id>
   ```

5. **Slow-day gate.** Read `runs/<run_id>/corpus.json` and `min_corpus_for_clustering` from `config.json`. Compare the corpus length to the threshold:

   - **If `len(corpus) < min_corpus_for_clustering`:** the day is too quiet to manufacture topics. Write `runs/<run_id>/skipped_clustering.json` and **skip steps 6 and 7** — jump straight to step 8 (render + dispatch), which will take the light-signal path. Do **not** write `trending_topics.json` or `content_recommendations.json`.

     ```
     uv run python -c "import json; from pathlib import Path; corpus=json.loads(Path('runs/<run_id>/corpus.json').read_text(encoding='utf-8')); Path('runs/<run_id>/skipped_clustering.json').write_text(json.dumps({'reason': 'corpus below clustering threshold', 'corpus_size': len(corpus)}), encoding='utf-8')"
     ```

   - **Otherwise:** continue to step 6 as normal.

6. **Cluster.** Read `prompts/clustering_prompt.md` and the full contents of `runs/<run_id>/corpus.json`. Spawn **one** subagent (`subagent_type=general-purpose`, `model=sonnet`, fresh context). Its prompt is the clustering prompt, then the corpus JSON inlined verbatim, then two lines:

   ```
   Run ID: <run_id>
   Output path: runs/<run_id>/trending_topics.json
   ```

   After it returns, inspect `runs/<run_id>/trending_topics.json`. If it is missing or does not parse as `{topics: [...], other_notable: [...]}`, log a `warning` (step `cluster`) and write a fallback so the pipeline continues:

   ```
   uv run python -c "from pathlib import Path; Path('runs/<run_id>/trending_topics.json').write_text('{\"topics\": [], \"other_notable\": []}', encoding='utf-8')"
   ```

7. **Recommend.** Read `prompts/recommendations_prompt.md`, the full contents of `runs/<run_id>/trending_topics.json`, and `content_channels` from `config.json`. Spawn **one** subagent (same harness, fresh context). Its prompt is the recommendations prompt, then the trending-topics JSON inlined verbatim, then the channel list as plain prose and the run lines. For example:

   ```
   Channels to write for: substack, linkedin, instagram
   Run ID: <run_id>
   Output path: runs/<run_id>/content_recommendations.json
   ```

   After it returns, inspect `runs/<run_id>/content_recommendations.json`. If it is missing or does not parse as a JSON array, log a `warning` (step `recommend`) and write a fallback:

   ```
   uv run python -c "from pathlib import Path; Path('runs/<run_id>/content_recommendations.json').write_text('[]', encoding='utf-8')"
   ```

   Clustering and recommendations are a strict dependency chain — run them sequentially, not in a single tool block.

8. **Render + dispatch.** Bash:

   ```
   uv run python -m scripts.send_email <run_id>
   ```

9. **Final console line.** Read `runs/<run_id>/corpus.json`, `runs/<run_id>/trending_topics.json`, `runs/<run_id>/content_recommendations.json`, and `runs/<run_id>/errors.log`. Print one line:

   ```
   run_id=<run_id> items=<n> topics=<t> ideas=<i> errors=<m> email=<mode>:<id>
   ```

   `topics` is the number of entries in `trending_topics.json` `topics[]`. `ideas` is the total number of idea entries across all recommendations (sum of each recommendation's `ideas` map size). `errors` counts `errors.log` entries with `severity == "error"`. `email` is parsed from the dispatch step output. On a slow-day run the gate skipped synthesis, so `trending_topics.json` and `content_recommendations.json` are absent — report `topics=0 ideas=0`.

## Non-fatal handling

Subagent or fetch failures land in `errors.log` (warning/info) and the pipeline continues — an empty source is expected, not a failure. A clustering or recommendations subagent that produces no valid file gets a logged `warning` plus an empty-but-valid fallback file, so the email still renders (as an empty topic-card digest) rather than aborting. Uncaught Python exceptions from any script abort the run and surface the failing step.
