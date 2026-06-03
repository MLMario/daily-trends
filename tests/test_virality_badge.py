"""Behavior tests for scripts.lib.virality_badge.

The Virality score is the reusable, deterministic seam introduced with LinkedIn
virality scoring (issue #39): it maps a 1-10 composite to a red->amber->green
color band, from a weighted average over a channel's rubric. Instagram (issue
#40) reuses the same component, so the band thresholds and the weights live here
once, tested, rather than duplicated per channel. The *markup* lives in the
report template (class-based, keyed on the band these functions return); only the
math is extracted here (ADR-0005).
"""

from __future__ import annotations

from scripts.lib.virality_badge import (
    INSTAGRAM_RUBRIC,
    LINKEDIN_RUBRIC,
    band_for_score,
    composite_score,
)


def test_low_composite_is_the_red_band() -> None:
    assert band_for_score(1) == "red"
    assert band_for_score(4) == "red"


def test_mid_composite_is_the_amber_band() -> None:
    assert band_for_score(5) == "amber"
    assert band_for_score(7) == "amber"


def test_high_composite_is_the_green_band() -> None:
    assert band_for_score(8) == "green"
    assert band_for_score(10) == "green"


def test_linkedin_rubric_weights_match_the_spec() -> None:
    assert LINKEDIN_RUBRIC == {
        "Hook Tension": 0.25,
        "Opinion Sharpness": 0.25,
        "Narrative Structure": 0.20,
        "Niche Fit": 0.20,
        "Saveability": 0.10,
    }


def test_instagram_rubric_weights_match_the_spec() -> None:
    assert INSTAGRAM_RUBRIC == {
        "3-Second Hook": 0.30,
        "Emotional Valence / Send-impulse": 0.25,
        "Completability / Pacing": 0.25,
        "Universality of Premise": 0.10,
        "Audio / Trend Leverage": 0.10,
    }


SUBSCORES = {
    "Hook Tension": 9,
    "Opinion Sharpness": 8,
    "Narrative Structure": 7,
    "Niche Fit": 8,
    "Saveability": 6,
}


def test_composite_is_the_rounded_weighted_average_of_subscores() -> None:
    # 9*.25 + 8*.25 + 7*.20 + 8*.20 + 6*.10 = 2.25+2+1.4+1.6+0.6 = 7.85 -> 8
    assert composite_score(SUBSCORES, LINKEDIN_RUBRIC) == 8


def test_composite_of_uniform_tens_is_ten() -> None:
    perfect = {dim: 10 for dim in LINKEDIN_RUBRIC}
    assert composite_score(perfect, LINKEDIN_RUBRIC) == 10


def test_composite_rounds_half_up_at_a_tie() -> None:
    # The prompt mandates "ties round half up" (report_prompt.md), and this
    # helper is the canonical source of the composite math (ADR-0005). A .5 tie
    # must round UP, not to-even — banker's rounding would flip the band.
    #
    # 6*.25 + 4*.25 + 4*.20 + 4*.20 + 4*.10 = 1.5 + 1.0 + 0.8 + 0.8 + 0.4 = 4.5
    half_tie = {
        "Hook Tension": 6,
        "Opinion Sharpness": 4,
        "Narrative Structure": 4,
        "Niche Fit": 4,
        "Saveability": 4,
    }
    # round-half-up: 4.5 -> 5, NOT 4 (round-half-to-even would give 4).
    assert composite_score(half_tie, LINKEDIN_RUBRIC) == 5
    # And the band flips with it: 4 is red, 5 is amber. The tie must land amber.
    assert band_for_score(composite_score(half_tie, LINKEDIN_RUBRIC)) == "amber"


def test_instagram_rubric_weights_sum_to_one() -> None:
    # The composite is a weighted average; if the weights drifted off 1.0 the
    # composite would no longer be on the 1-10 scale the bands assume.
    assert sum(INSTAGRAM_RUBRIC.values()) == 1.0


def test_instagram_composite_is_the_rounded_weighted_average_of_subscores() -> None:
    # `instagram` reuses the same `composite_score`/bands as `linkedin`
    # (ADR-0005) — only the rubric differs. Score an IG Reel concept:
    # 9*.30 + 8*.25 + 7*.25 + 6*.10 + 5*.10 = 2.7+2.0+1.75+0.6+0.5 = 7.55 -> 8
    ig_subscores = {
        "3-Second Hook": 9,
        "Emotional Valence / Send-impulse": 8,
        "Completability / Pacing": 7,
        "Universality of Premise": 6,
        "Audio / Trend Leverage": 5,
    }
    assert composite_score(ig_subscores, INSTAGRAM_RUBRIC) == 8
    assert band_for_score(composite_score(ig_subscores, INSTAGRAM_RUBRIC)) == "green"


def test_instagram_composite_rounds_half_up_at_a_tie() -> None:
    # Same round-half-up rule as LinkedIn, exercised through the IG weights.
    # 7*.30 + 4*.25 + 4*.25 + 2*.10 + 2*.10 = 2.1+1.0+1.0+0.2+0.2 = 4.5
    half_tie = {
        "3-Second Hook": 7,
        "Emotional Valence / Send-impulse": 4,
        "Completability / Pacing": 4,
        "Universality of Premise": 2,
        "Audio / Trend Leverage": 2,
    }
    assert composite_score(half_tie, INSTAGRAM_RUBRIC) == 5
    assert band_for_score(composite_score(half_tie, INSTAGRAM_RUBRIC)) == "amber"
