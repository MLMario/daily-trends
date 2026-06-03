"""The Virality score math — the rubric weights, composite, and color band.

Introduced with LinkedIn virality scoring (issue #39) and reused unchanged by
Instagram (issue #40). A channel's Virality cell, once it has a rubric, surfaces
a 1-10 composite as a color-banded score (red->amber->green) with the five
per-dimension sub-scores and a 2-sentence justification beside it. The weights
and the band thresholds live here once so both channels share one tested seam
rather than duplicating the bands in two report prompts.

This module holds the *deterministic* fraction of the score — the weights, the
composite formula, and the band thresholds. The **markup** is not here: the
master-detail report (ADR-0004, HTML-direct) colors its scorebox and sub-score
meters via CSS classes defined in `templates/report_template.html` (e.g.
`scorebox green`, `meter amber`), keyed on the band this module computes. There
is no inline-CSS badge component to render — the subagent authors the card HTML
straight from the template, so the only thing worth extracting is the math.

Bands (1-10 composite):
  1-4  -> red    (a weak bet)
  5-7  -> amber  (a contender)
  8-10 -> green  (the operator's best bet)
"""

from __future__ import annotations

import math

# The LinkedIn rubric (issue #39): a weighted composite over five dimensions,
# each judged 1-10 from the Idea text + Topic context (no engagement metrics).
# The 1->10 anchor descriptions live in prompts/report_prompt.md; the *weights*
# live here so the composite is computed identically everywhere it is needed.
LINKEDIN_RUBRIC: dict[str, float] = {
    "Hook Tension": 0.25,
    "Opinion Sharpness": 0.25,
    "Narrative Structure": 0.20,
    "Niche Fit": 0.20,
    "Saveability": 0.10,
}

# The Instagram Reels rubric (issue #40): the same weighted-composite shape, but
# tuned for short-form video — a Reel concept judged 1-10 from the Idea text +
# Topic context (no Reel engagement metrics). The 1->10 anchor descriptions live
# in prompts/report_prompt.md; the *weights* live here so `instagram` composites
# are computed by the same `composite_score` as `linkedin` (ADR-0005).
INSTAGRAM_RUBRIC: dict[str, float] = {
    "3-Second Hook": 0.30,
    "Emotional Valence / Send-impulse": 0.25,
    "Completability / Pacing": 0.25,
    "Universality of Premise": 0.10,
    "Audio / Trend Leverage": 0.10,
}


def composite_score(subscores: dict[str, int], rubric: dict[str, float]) -> int:
    """Weighted average of the per-dimension sub-scores, rounded to a 1-10 int.

    `rubric` maps each dimension to its weight (weights sum to 1.0). Only the
    dimensions present in the rubric contribute, so a channel's rubric fully
    determines its composite.

    Ties round half UP (4.5 -> 5), matching the rule the report prompt states
    for this composite. Python's built-in ``round`` is round-half-to-even
    (banker's rounding), which would send 4.5 -> 4 and flip the badge band, so
    ``math.floor(total + 0.5)`` is used instead.
    """
    total = sum(subscores[dimension] * weight for dimension, weight in rubric.items())
    return math.floor(total + 0.5)


def band_for_score(score: int) -> str:
    """Map a 1-10 composite Virality score to its color band.

    The same red/amber/green vocabulary names a CSS class in the report template:
    a scorebox carries the *composite's* band, while each sub-score meter carries
    *its own* band (so a 7 reads amber even inside an otherwise-green card).
    """
    if score <= 4:
        return "red"
    if score <= 7:
        return "amber"
    return "green"
