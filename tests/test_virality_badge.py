"""Behavior tests for scripts.lib.virality_badge.

The virality badge is the reusable, deterministic seam introduced with LinkedIn
virality scoring (issue #39): it maps a 1-10 composite Virality score to a
red->amber->green color band and renders a self-contained, inline-CSS badge with
the five per-dimension sub-scores and a 2-sentence justification beneath it.
Instagram (issue #40) reuses the same component, so the band thresholds and the
rendered markup live here once, tested, rather than duplicated per channel.
"""

from __future__ import annotations

from scripts.lib.virality_badge import (
    LINKEDIN_RUBRIC,
    band_for_score,
    composite_score,
    render_badge,
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


SUBSCORES = {
    "Hook Tension": 9,
    "Opinion Sharpness": 8,
    "Narrative Structure": 7,
    "Niche Fit": 8,
    "Saveability": 6,
}


def test_badge_shows_the_composite_score() -> None:
    out = render_badge(
        composite=8,
        subscores=SUBSCORES,
        justification="Strong, opinionated hook. Lands squarely in the niche.",
    )
    assert "8" in out


def test_badge_carries_its_band_color_class() -> None:
    red = render_badge(composite=3, subscores=SUBSCORES, justification="Weak. Flat.")
    amber = render_badge(composite=6, subscores=SUBSCORES, justification="Okay. Middling.")
    green = render_badge(composite=9, subscores=SUBSCORES, justification="Sharp. Saveable.")
    assert "virality-badge--red" in red
    assert "virality-badge--amber" in amber
    assert "virality-badge--green" in green


def test_badge_lists_every_dimension_and_its_subscore() -> None:
    out = render_badge(
        composite=8,
        subscores=SUBSCORES,
        justification="Strong. Lands.",
    )
    for dimension, value in SUBSCORES.items():
        assert dimension in out
        assert str(value) in out


def test_badge_shows_the_justification() -> None:
    out = render_badge(
        composite=8,
        subscores=SUBSCORES,
        justification="The hook provokes. The niche fit is exact.",
    )
    assert "The hook provokes. The niche fit is exact." in out


def test_badge_escapes_interpolated_justification() -> None:
    out = render_badge(
        composite=8,
        subscores=SUBSCORES,
        justification='A <script> & "quote" angle.',
    )
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_badge_is_self_contained_no_external_assets() -> None:
    out = render_badge(composite=8, subscores=SUBSCORES, justification="X. Y.")
    assert "http://" not in out
    assert "https://" not in out
    assert "<link" not in out
    assert "<script" not in out


def test_linkedin_rubric_weights_match_the_spec() -> None:
    assert LINKEDIN_RUBRIC == {
        "Hook Tension": 0.25,
        "Opinion Sharpness": 0.25,
        "Narrative Structure": 0.20,
        "Niche Fit": 0.20,
        "Saveability": 0.10,
    }


def test_composite_is_the_rounded_weighted_average_of_subscores() -> None:
    # 9*.25 + 8*.25 + 7*.20 + 8*.20 + 6*.10 = 2.25+2+1.4+1.6+0.6 = 7.85 -> 8
    assert composite_score(SUBSCORES, LINKEDIN_RUBRIC) == 8


def test_composite_of_uniform_tens_is_ten() -> None:
    perfect = {dim: 10 for dim in LINKEDIN_RUBRIC}
    assert composite_score(perfect, LINKEDIN_RUBRIC) == 10
