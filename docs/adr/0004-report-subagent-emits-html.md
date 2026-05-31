# ADR 0004 — The report subagent emits HTML directly

**Status:** accepted (2026-05-29). Introduced with the scoreless per-channel **Report** slice (issue #38, parent #37).

## Decision

The new **report subagent** emits **HTML directly** — it is handed a self-contained, inline-CSS HTML template (`templates/report_template.html`) plus its data inputs and writes the finished `runs/<run_id>/report.html`. This **deviates** from the repo's established convention that *subagents emit JSON and Python code renders*. The clustering and recommendations subagents both write structured JSON (`trending_topics.json`, `content_recommendations.json`) that the deterministic `EmailRenderer` then turns into the Digest's HTML. The report subagent owns rendering end-to-end instead: there is **no** `ReportRenderer` and **no** intermediate JSON scores file.

## Context

The Report is a per-run, idea-centric deliverable grouped by **Channel**, produced alongside the Digest and attached to the same email. This first slice ships the full path through every layer **without** virality scoring — the Virality column reads `—` for all channels — so the only moving parts are: resolve each Topic's **Sources** from the corpus, lay ideas out in a Channel-grouped table, and produce a file that renders correctly when opened directly from disk.

Two shapes were possible:

1. **Subagent → JSON scores → `ReportRenderer` → HTML** (mirror the Digest). A `report_scores.json` artifact, a new deterministic renderer module, and a template the renderer fills.
2. **Subagent → HTML** (this ADR). The subagent fills the template itself; its sole artifact is `report.html`.

## Rationale

- **Nothing to compute deterministically yet.** In this slice the report carries no scores — every Virality cell is `—`. A JSON-scores-then-render split exists to keep a deterministic, testable boundary around *computation*. There is no computation here, so the split would buy an empty intermediate file and a renderer that does pure string substitution the subagent can do itself.
- **The deterministic seam that matters is elsewhere and already tested.** The load-bearing, regression-prone behaviors — *which* artifacts attach to the email, and the slow-day / report-failure guards — live in `scripts.send_email.gather_attachments` and are covered by `tests/test_send_email.py`. The report's **presence/absence** is deterministic Python behind an existence guard; its **content** is the subagent's job. That is the right boundary.
- **HTML is the natural output of this stage.** The Report is a visual artifact whose value is layout and readability. Letting the subagent render directly keeps the template authorial and avoids a renderer that must re-encode every layout decision in Python.
- **Reversible.** When virality scoring lands (the parent #37 work), the decision is revisited: scores are real computation and may warrant a `report_scores.json` + `ReportRenderer` split, OR the subagent may continue to render with scores handed to it. This ADR explicitly scopes the HTML-direct decision to the scoreless slice and flags the re-evaluation trigger below.

## Consequences

- A new `prompts/report_prompt.md` and a new `templates/report_template.html` (self-contained, inline CSS, no network) are the report subagent's contract. The template renders Channel sections in the configured order, each a three-column **Idea | Resources | Virality** table, one row per Topic.
- The report subagent writes `runs/<run_id>/report.html` as its **sole** artifact. No JSON scores file is written.
- `RunWorkspace.report` exposes the typed path; the report step is **non-fatal with no fallback** — a missing/unreadable `report.html` logs a `warning` under step `report` and the run still ships its Digest.
- `scripts.send_email.gather_attachments` adds `report.html` to the attachment list behind an existence guard, so a slow day (report step skipped) or a failed report step omits the attachment with no special-casing.
- The Channel set is **data-driven**: the subagent renders exactly the configured `content_channels`, with no hardcoded channel names — consistent with how the recommendations `ideas` map is keyed by channel.

## When this ADR would be re-evaluated

- **Virality scoring lands (parent #37).** Real scoring is deterministic computation that benefits from a testable seam. At that point, decide between (a) `report_scores.json` + a `ReportRenderer` that sorts/labels deterministically, or (b) handing computed scores to the subagent and keeping HTML-direct rendering. Either way the scoreless-slice rationale above no longer fully applies.
- **The report needs cross-run or interactive behavior.** Any logic that must be identical across runs, unit-tested in isolation, or driven by operator config beyond the channel list pushes toward a deterministic renderer.
