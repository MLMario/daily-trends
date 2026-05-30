"""The reusable Virality badge — score-to-color band + self-contained badge HTML.

Introduced with LinkedIn virality scoring (issue #39) and reused unchanged by
Instagram (issue #40). A channel's Virality cell, once it has a rubric, renders a
1-10 composite as a color-coded badge (red->amber->green) with the five
per-dimension sub-scores and a 2-sentence justification beneath. The band
thresholds and the inline-CSS markup live here once so both channels share one
tested component rather than duplicating the bands in two report prompts.

Bands (1-10 composite):
  1-4  -> red    (a weak bet)
  5-7  -> amber  (a contender)
  8-10 -> green  (the operator's best bet)
"""

from __future__ import annotations

import html
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
# are computed by the same `composite_score` as `linkedin`, reusing the badge
# component unchanged (ADR-0005).
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
    """Map a 1-10 composite Virality score to its color band."""
    if score <= 4:
        return "red"
    if score <= 7:
        return "amber"
    return "green"


# Inline-CSS colors per band — self-contained so the badge renders from disk
# with no network, stylesheet, or font dependency (ADR-0004's constraint).
_BAND_BG = {"red": "#e5534b", "amber": "#d9a514", "green": "#2da44e"}


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def render_badge(*, composite: int, subscores: dict[str, int], justification: str) -> str:
    """Render the Virality badge: the color-coded composite, with the five
    per-dimension sub-scores and the 2-sentence justification beneath it.

    A reusable component (LinkedIn now, Instagram next): every scored channel's
    Virality cell renders this exact markup, so the band thresholds and styling
    live in one tested place. Self-contained inline CSS — no external assets.
    """
    band = band_for_score(composite)
    bg = _BAND_BG[band]
    badge = (
        f'<span class="virality-badge virality-badge--{band}" '
        f'style="display:inline-block;min-width:28px;padding:3px 9px;border-radius:12px;'
        f'background:{bg};color:#fff;font-weight:700;font-size:13px;text-align:center;">'
        f"{_esc(str(composite))}/10</span>"
    )
    sub_rows = "".join(
        f'<li style="margin:0;"><span style="color:#666;">{_esc(dimension)}:</span> '
        f"{_esc(str(value))}</li>"
        for dimension, value in subscores.items()
    )
    subscores_block = (
        f'<ul class="virality-subscores" '
        f'style="list-style:none;margin:6px 0 0;padding:0;font-size:11px;line-height:1.5;">'
        f"{sub_rows}</ul>"
    )
    justification_block = (
        f'<p class="virality-justification" '
        f'style="margin:6px 0 0;font-size:11px;color:#444;line-height:1.4;">'
        f"{_esc(justification)}</p>"
    )
    return (
        '<div class="virality-cell" style="vertical-align:top;">'
        f"{badge}{subscores_block}{justification_block}"
        "</div>"
    )
