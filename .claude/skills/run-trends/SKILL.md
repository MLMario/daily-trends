---
name: run-trends
description: Run the daily-trends pipeline end-to-end against today's news and deliver a Gmail draft. Use when the user says "/run-trends", "run daily trends", "send today's trends digest", or asks to trigger the trends pipeline.
---

# run-trends

Orchestrate the pipeline: pre-flight → news + vendor-blogs subagents (parallel) → normalize → cluster → recommend → render + dispatch the topic-card email.

## Steps

1. **Pre-flight + new run.** Bash:

   ```
   uv run python -m scripts.init_run
   ```

   Capture the printed `run_id` (single line on stdout). On non-zero exit, surface the stderr message and abort.

2. **Fetch both sources concurrently.** Read `prompts/news_search_prompt.md` and `prompts/vendor_blogs_prompt.md`, and read `vendor_blogs` + `vendor_blogs_lookback_days` from `config.json`.

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

   Issue **both** Agent calls in a **single tool block** so they run in parallel. Both use `subagent_type=general-purpose`, `model=sonnet`, fresh context, WebFetch available.

3. **Record source-fetch outcomes (non-fatal).** After both subagents return, inspect each output file. None of these abort the run:

   - A subagent's output file is missing or unparseable → log a `warning` (step `fetch`) and continue.
   - `runs/<run_id>/vendor_blogs/posts.json` is an empty array → log an **`info`**-level note (step `fetch`) that no vendor-blog posts fell in the lookback window. This is normal, **not an error**.

   Append events with the `ErrorLog` helper so each line matches the JSON-lines schema, e.g.:

   ```
   uv run python -c "from pathlib import Path; from scripts.lib.error_log import ErrorLog; ErrorLog(Path('runs/<run_id>/errors.log')).log(step='fetch', severity='info', message='vendor_blogs: no posts in the lookback window')"
   ```

4. **Normalize.** Bash:

   ```
   uv run python -m scripts.normalize_corpus <run_id>
   ```

5. **Cluster.** Read `prompts/clustering_prompt.md` and the full contents of `runs/<run_id>/corpus.json`. Spawn **one** subagent (`subagent_type=general-purpose`, `model=sonnet`, fresh context). Its prompt is the clustering prompt, then the corpus JSON inlined verbatim, then two lines:

   ```
   Run ID: <run_id>
   Output path: runs/<run_id>/trending_topics.json
   ```

   After it returns, inspect `runs/<run_id>/trending_topics.json`. If it is missing or does not parse as `{topics: [...], other_notable: [...]}`, log a `warning` (step `cluster`) and write a fallback so the pipeline continues:

   ```
   uv run python -c "from pathlib import Path; Path('runs/<run_id>/trending_topics.json').write_text('{\"topics\": [], \"other_notable\": []}', encoding='utf-8')"
   ```

6. **Recommend.** Read `prompts/recommendations_prompt.md`, the full contents of `runs/<run_id>/trending_topics.json`, and `content_channels` from `config.json`. Spawn **one** subagent (same harness, fresh context). Its prompt is the recommendations prompt, then the trending-topics JSON inlined verbatim, then the channel list as plain prose and the run lines. For example:

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

7. **Render + dispatch.** Bash:

   ```
   uv run python -m scripts.send_email <run_id>
   ```

8. **Final console line.** Read `runs/<run_id>/corpus.json`, `runs/<run_id>/trending_topics.json`, `runs/<run_id>/content_recommendations.json`, and `runs/<run_id>/errors.log`. Print one line:

   ```
   run_id=<run_id> items=<n> topics=<t> ideas=<i> errors=<m> email=<mode>:<id>
   ```

   `topics` is the number of entries in `trending_topics.json` `topics[]`. `ideas` is the total number of idea entries across all recommendations (sum of each recommendation's `ideas` map size). `errors` counts `errors.log` entries with `severity == "error"`. `email` is parsed from the dispatch step output.

## Non-fatal handling

Subagent or fetch failures land in `errors.log` (warning/info) and the pipeline continues — an empty source is expected, not a failure. A clustering or recommendations subagent that produces no valid file gets a logged `warning` plus an empty-but-valid fallback file, so the email still renders (as an empty topic-card digest) rather than aborting. Uncaught Python exceptions from any script abort the run and surface the failing step.
