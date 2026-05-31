# ADR 0005 — Virality scoring stays subagent-judged; the badge math is extracted

**Status:** accepted (2026-05-30). Introduced with LinkedIn virality scoring (issue #39, parent #37). Resolves the re-evaluation trigger flagged in ADR-0004 ("Virality scoring lands (parent #37)").

## Decision

When **Virality scoring** lands, the report subagent **keeps emitting HTML directly** (ADR-0004 stands) and **judges the scores itself** — it is **not** split into a `report_scores.json` + a `ReportRenderer`. The per-dimension sub-scores and the 2-sentence justification are an LLM judgment of an *unpublished* Idea against a **rubric**, read from the Idea text + Topic context only; there is nothing for deterministic Python to compute there.

What **is** deterministic and reusable is extracted to a tested module, `scripts/lib/virality_badge.py`:

- the **LinkedIn rubric weights** (`LINKEDIN_RUBRIC`),
- the **composite** = rounded weighted average of the sub-scores (`composite_score`),
- the **color band** thresholds red ≤ 4 / amber 5–7 / green ≥ 8 (`band_for_score`),
- the **badge HTML** — a self-contained, inline-CSS component (`render_badge`).

The report prompt and template reference this module as the canonical source of the weights, bands, and badge markup; the subagent renders the badge from the template's copy of that markup. ADR-0004's option (b) (hand-computed-or-judged scores, HTML-direct) is chosen over option (a) (JSON scores + a renderer).

## Context

ADR-0004 scoped HTML-direct rendering to the scoreless slice and named two re-evaluation triggers, the first being "Virality scoring lands." Issue #39 is that slice for `linkedin`: a 1–10 composite per Idea from a weighted five-dimension rubric, rendered as a red→amber→green badge, with the `linkedin` section sorted by composite descending, while `substack` stays `—` in Topic order. The scored-vs-scoreless split keys off **rubric presence**, not a channel name.

Two shapes were again possible:

1. **Subagent → `report_scores.json` → `ReportRenderer` → HTML.** A deterministic renderer sorts and labels; the subagent only emits structured scores.
2. **Subagent → HTML, badge math extracted.** The subagent judges + renders; the weights/bands/markup live in a tested helper both it (via the prompt/template) and the next channel reuse.

## Rationale

- **The score is a judgment, not a computation.** The sub-scores rate an Idea that has never been published — there are no engagement metrics to crunch. That work is irreducibly the model's; a `ReportRenderer` would render *someone else's* numbers without adding a deterministic guarantee over how they were derived.
- **But the band, the weights, and the badge markup _are_ deterministic and _are_ reused.** Issue #40 (`instagram`) reuses the exact badge component. Duplicating "red ≤ 4, amber 5–7, green ≥ 8" and the weighted-average formula across two report prompts is the kind of drift-prone repetition a tested seam exists to kill. So that — and only that — is extracted to `scripts/lib/virality_badge.py` with unit tests.
- **Minimal, reversible deviation from ADR-0004.** HTML-direct rendering and the no-intermediate-JSON-scores-file decision both stand; the only change is that the reusable, deterministic fraction of the new behavior now has a tested home instead of living solely in prose.

## Consequences

- `scripts/lib/virality_badge.py` is the single source of truth for the LinkedIn rubric weights, the composite math, the color bands, and the badge HTML; `tests/test_virality_badge.py` pins them.
- `prompts/report_prompt.md` carries the rubric's 1→10 anchor descriptions and instructs the subagent to score scored channels, render the badge, and sort scored sections by composite descending — keyed on **rubric presence**, not a channel name.
- `templates/report_template.html` embeds the canonical badge markup as a reusable block and renders the Virality cell as either `—` (scoreless) or the badge (scored).
- Still **no** `report_scores.json` and **no** `ReportRenderer`; the subagent's sole artifact remains `runs/<run_id>/report.html`.
- Adding the next scored channel (issue #40, `instagram`) reuses `virality_badge.py` and adds only its own rubric anchors to the prompt — no new rendering code.

## When this ADR would be re-evaluated

- **Scores need to be deterministic, diffable, or sorted/relabeled outside the model.** If a future slice must re-rank across runs, recompute composites from stored sub-scores, or expose scores to another consumer, a `report_scores.json` + `ReportRenderer` split becomes worth its cost and supersedes the HTML-direct judgment here.
