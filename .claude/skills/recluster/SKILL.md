---
name: recluster
description: Re-synthesize a prior run's corpus without re-fetching news. Use when the user says "/recluster <source_run_id>", wants to re-cluster an existing run, or is tuning clustering_prompt.md / recommendations_prompt.md and wants to iterate cheaply without reshuffling the input.
---

# recluster

Re-run synthesis + email against an **existing** run's corpus, instead of fetching fresh news. The source corpus is reused byte-for-byte, so prompt iteration (`clustering_prompt.md`, `recommendations_prompt.md`) is cheap and repeatable — HN's front page can't shuffle the input out from under you between runs.

A recluster creates its own fresh, immutable `runs/<new_id>/`. The source run is **read-only** — nothing under `runs/<source_run_id>/` is ever written.

## Argument

`<source_run_id>` — the run id to reuse the corpus from (positional, required). For example: `/recluster 2026-05-27T01-13Z`.

## Stage-boundary timing

A recluster skips the fetch + normalize stages, so it logs markers only for the stages it actually runs. Append one **pure-info** entry (no `kind`) at the start of each numbered step from 4 onward, using these step tokens: `recluster` (right after step 2 creates the run dir), then `slow-day`, `cluster`, `recommend`, `render`. Same convention as `/run-trends` — see `.claude/skills/run-trends/SKILL.md` "Stage-boundary timing". Skip the `cluster` / `recommend` markers when the slow-day gate skips those stages. Example:

```
uv run python -c "from pathlib import Path; from scripts.lib.error_log import ErrorLog; ErrorLog(Path('runs/<new_id>/errors.log')).log(step='recluster', severity='info', message='stage start: recluster of <source_run_id>')"
```

## Steps

1. **Validate the source (abort fast, before creating anything).** A bad `<source_run_id>` must fail immediately, without minting a stray run directory. Bash:

   ```
   uv run python -c "import sys; from pathlib import Path; src=Path('runs/<source_run_id>/corpus.json'); sys.exit(0 if src.is_file() else f'recluster: source run <source_run_id> not found or missing corpus.json ({src})')"
   ```

   On non-zero exit, surface the stderr message and abort. Do **not** proceed to step 2.

2. **Pre-flight + new run.** Reuses `/run-trends` step 1 unchanged. Bash:

   ```
   uv run python -m scripts.init_run
   ```

   Capture the printed `run_id` (single line on stdout) — this is `<new_id>`, distinct from the source. On non-zero exit, surface the stderr message and abort.

3. **Reuse the corpus + record lineage.** Copy the source corpus byte-identical into the new run (`copyfile` reads the source only — it never writes to it), then write the provenance record via the canonical `lineage_record` builder so the schema stays single-sourced in code:

   ```
   uv run python -c "import shutil; shutil.copyfile('runs/<source_run_id>/corpus.json', 'runs/<new_id>/corpus.json')"
   ```

   ```
   uv run python -c "import json; from pathlib import Path; from scripts.lib.run_workspace import lineage_record; Path('runs/<new_id>/lineage.json').write_text(json.dumps(lineage_record('<source_run_id>', reused=['corpus.json'])), encoding='utf-8')"
   ```

   `runs/<new_id>/lineage.json` now holds `{source_run_id, reused: ["corpus.json"], created_at}`.

4. **Slow-day gate.** Run `/run-trends` **step 5** exactly, against `<new_id>`: read `runs/<new_id>/corpus.json` and `min_corpus_for_clustering` from `config.json`. If `len(corpus) < min_corpus_for_clustering`, write `runs/<new_id>/skipped_clustering.json` and **skip steps 5 and 6** — jump to step 7 (render + dispatch), which takes the light-signal path. Otherwise continue.

   ```
   uv run python -c "import json; from pathlib import Path; corpus=json.loads(Path('runs/<new_id>/corpus.json').read_text(encoding='utf-8')); Path('runs/<new_id>/skipped_clustering.json').write_text(json.dumps({'reason': 'corpus below clustering threshold', 'corpus_size': len(corpus)}), encoding='utf-8')"
   ```

5. **Cluster.** Run `/run-trends` **step 6** exactly, against `<new_id>`: read `prompts/clustering_prompt.md` and the full contents of `runs/<new_id>/corpus.json`, spawn **one** subagent (`subagent_type=general-purpose`, `model=sonnet`, fresh context) whose prompt is the clustering prompt, then the corpus JSON inlined verbatim, then:

   ```
   Run ID: <new_id>
   Output path: runs/<new_id>/trending_topics.json
   ```

   After it returns, inspect `runs/<new_id>/trending_topics.json`. If missing or not parseable as `{topics: [...], other_notable: [...]}`, log a `warning` (step `cluster`) and write the fallback so the pipeline continues:

   ```
   uv run python -c "from pathlib import Path; Path('runs/<new_id>/trending_topics.json').write_text('{\"topics\": [], \"other_notable\": []}', encoding='utf-8')"
   ```

6. **Recommend.** Run `/run-trends` **step 7** exactly, against `<new_id>`: read `prompts/recommendations_prompt.md`, the full contents of `runs/<new_id>/trending_topics.json`, and `content_channels` from `config.json`. Spawn **one** subagent (same harness, fresh context) whose prompt is the recommendations prompt, then the trending-topics JSON inlined verbatim, then the channel list as plain prose and the run lines:

   ```
   Channels to write for: substack, linkedin, instagram
   Run ID: <new_id>
   Output path: runs/<new_id>/content_recommendations.json
   ```

   After it returns, inspect `runs/<new_id>/content_recommendations.json`. If missing or not a JSON array, log a `warning` (step `recommend`) and write the fallback:

   ```
   uv run python -c "from pathlib import Path; Path('runs/<new_id>/content_recommendations.json').write_text('[]', encoding='utf-8')"
   ```

   Clustering and recommendations are a strict dependency chain — run them sequentially, not in a single tool block.

7. **Render + dispatch.** Run `/run-trends` **step 8** exactly, against `<new_id>`. Bash:

   ```
   uv run python -m scripts.send_email <new_id>
   ```

8. **Final console line.** As in `/run-trends` step 9, but labelled as a recluster so the run's provenance is obvious. Read `runs/<new_id>/corpus.json`, `runs/<new_id>/trending_topics.json`, `runs/<new_id>/content_recommendations.json`, and `runs/<new_id>/errors.log`, then print:

   ```
   recluster run_id=<new_id> source=<source_run_id> items=<n> topics=<t> ideas=<i> errors=<m> email=<mode>:<id>
   ```

   `topics` is the number of entries in `trending_topics.json` `topics[]`. `ideas` is the total idea entries across all recommendations (sum of each recommendation's `ideas` map size). `errors` counts `errors.log` entries with `severity == "error"`. `email` is parsed from the dispatch step output. On a slow-day recluster the gate skipped synthesis, so report `topics=0 ideas=0`.

## Non-fatal handling

Identical to `/run-trends`: a clustering or recommendations subagent that produces no valid file gets a logged `warning` plus an empty-but-valid fallback, so the email still renders rather than aborting. The only recluster-specific hard aborts are step 1 (unknown / corpus-less source) and step 2 (failed pre-flight). The source run is never modified.
