---
name: run-trends
description: Run the daily-trends pipeline end-to-end against today's news and deliver a Gmail draft. Use when the user says "/run-trends", "run daily trends", "send today's trends digest", or asks to trigger the trends pipeline.
---

# run-trends

Orchestrate the slice-3 skeleton: pre-flight → news + vendor-blogs subagents (parallel) → normalize → render + dispatch.

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

5. **Render + dispatch.** Bash:

   ```
   uv run python -m scripts.send_email <run_id>
   ```

6. **Final console line.** Read `runs/<run_id>/corpus.json` and `runs/<run_id>/errors.log`. Print one line:

   ```
   run_id=<run_id> items=<n> errors=<m> email=<mode>:<id>
   ```

   `errors` counts entries with `severity == "error"`. `email` is parsed from the dispatch step output.

## Non-fatal handling

Subagent or fetch failures land in `errors.log` (warning/info) and the pipeline continues — an empty source is expected, not a failure. Uncaught Python exceptions from any script abort the run and surface the failing step.
