---
name: recluster
description: Re-synthesize a prior run's corpus without re-fetching news. Use when the user says "/recluster <source_run_id>", wants to re-cluster an existing run, or is tuning clustering_prompt.md / recommendations_prompt.md and wants to iterate cheaply without reshuffling the input.
---

# recluster

Re-run synthesis + report + email against an **existing** run's corpus, instead of fetching fresh news. The source corpus is reused byte-for-byte, so prompt iteration (`clustering_prompt.md`, `recommendations_prompt.md`) is cheap and repeatable — HN's front page can't shuffle the input out from under you between runs.

A recluster creates its own fresh, immutable `runs/<new_id>/`. The source run is **read-only** — nothing under `runs/<source_run_id>/` is ever written.

## Argument

`<source_run_id>` — the run id to reuse the corpus from (positional, required). For example: `/recluster 2026-05-27T01-13Z`.

## Stage-boundary timing

A recluster skips the fetch + normalize stages, so it logs markers only for the stages it actually runs. Append one **pure-info** entry (no `kind`) at the start of each numbered step from 4 onward, using these step tokens: `recluster` (right after step 2 creates the run dir), then `slow-day`, `cluster`, `recommend`, `report`, `render`. Same convention as `/run-trends` — see `.claude/skills/run-trends/SKILL.md` "Stage-boundary timing". Skip the `cluster` / `recommend` / `report` markers when the slow-day gate skips those stages. Example:

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

> **Steps 4–9 delegate to `/run-trends` by stage *name*, not step number.** The numbers there shift whenever a stage is inserted (that is exactly why this skill drifted once already), but the stage names are stable. For each step below, open `/run-trends`'s same-named stage and run it exactly; recluster restates only its own deltas (the `<new_id>` paths, lineage, recluster console label) and never re-states drift-prone values like the subagent model — those live in `/run-trends` alone.

4. **Slow-day gate.** Run `/run-trends`'s **Slow-day gate** stage exactly, against `<new_id>`: read `runs/<new_id>/corpus.json` and `min_corpus_for_clustering` from `config.json`. If `len(corpus) < min_corpus_for_clustering`, write `runs/<new_id>/skipped_clustering.json` and **skip the Cluster, Recommend, and Report steps** — jump to the Render step, which takes the light-signal path. Otherwise continue.

   ```
   uv run python -c "import json; from pathlib import Path; corpus=json.loads(Path('runs/<new_id>/corpus.json').read_text(encoding='utf-8')); Path('runs/<new_id>/skipped_clustering.json').write_text(json.dumps({'reason': 'corpus below clustering threshold', 'corpus_size': len(corpus)}), encoding='utf-8')"
   ```

5. **Cluster.** Run `/run-trends`'s **Cluster** stage exactly, against `<new_id>` — same prompt (`prompts/clustering_prompt.md`), corpus inlining, subagent harness, **model**, and fallback as specified there; the only delta is that read/write paths use `runs/<new_id>/` and the run line is `Run ID: <new_id>` / `Output path: runs/<new_id>/trending_topics.json`. On a missing/unparseable result, log the `cluster` warning and write the empty-but-valid fallback exactly as `/run-trends` does.

6. **Recommend.** Run `/run-trends`'s **Recommend** stage exactly, against `<new_id>` — same prompt (`prompts/recommendations_prompt.md`), trending-topics inlining, `content_channels` list, subagent harness, **model**, and fallback; the deltas are the `runs/<new_id>/` paths and the `Run ID: <new_id>` / `Output path: runs/<new_id>/content_recommendations.json` run lines. On failure log the `recommend` warning and write the `[]` fallback. Clustering and recommendations are a strict dependency chain — run them sequentially, not in a single tool block.

7. **Report.** Run `/run-trends`'s **Report** stage exactly, against `<new_id>`. Skip entirely when `runs/<new_id>/skipped_clustering.json` exists (clustering and recommendations never ran — nothing to report, and no `report.html` is written). Otherwise emit the `report` stage-boundary marker, then spawn the report subagent exactly as specified there — same prompt (`prompts/report_prompt.md`), template (`templates/report_template.html`), the three run JSONs + `content_channels` inlining, subagent harness, and **model** — with `Run ID: <new_id>` / `Output path: runs/<new_id>/report.html`. It writes `report.html` as its sole artifact. Non-fatal and **no fallback file**: if it produces no readable `report.html`, log a `warning` (step `report`) and continue — the recluster still ships its Digest.

8. **Render + dispatch.** Run `/run-trends`'s **Render + dispatch** stage exactly, against `<new_id>`. `send_email` attaches `report.html` behind an existence guard, so a slow-day recluster (or a failed report step) simply omits the attachment. Bash:

   ```
   uv run python -m scripts.send_email <new_id>
   ```

9. **Final console line.** As in `/run-trends`'s **Final console line** stage, but labelled as a recluster so the run's provenance is obvious. Read `runs/<new_id>/corpus.json`, `runs/<new_id>/trending_topics.json`, `runs/<new_id>/content_recommendations.json`, and `runs/<new_id>/errors.log`, then print:

   ```
   recluster run_id=<new_id> source=<source_run_id> items=<n> topics=<t> ideas=<i> errors=<m> email=<mode>:<id>
   ```

   `topics` is the number of entries in `trending_topics.json` `topics[]`. `ideas` is the total idea entries across all recommendations (sum of each recommendation's `ideas` map size). `errors` counts `errors.log` entries with `severity == "error"`. `email` is parsed from the dispatch step output. On a slow-day recluster the gate skipped synthesis, so report `topics=0 ideas=0`.

## Non-fatal handling

Identical to `/run-trends`: a clustering or recommendations subagent that produces no valid file gets a logged `warning` plus an empty-but-valid fallback, so the email still renders rather than aborting. The report subagent is non-fatal too, but — as in `/run-trends`'s Report stage — **no** fallback file is written: a missing/unreadable `report.html` logs a `report` warning and `send_email` omits the attachment behind its existence guard. The only recluster-specific hard aborts are step 1 (unknown / corpus-less source) and step 2 (failed pre-flight). The source run is never modified.
