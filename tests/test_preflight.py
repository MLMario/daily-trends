"""Behavior tests for scripts.lib.preflight — the X opt-in gating decision.

Slice B.2 makes BRIGHT_DATA_KEY a prerequisite *only* when X accounts are
configured. These tests pin that conditional and the surrounding pre-flight
contract without touching the filesystem or the real environment.
"""

from __future__ import annotations

from scripts.lib.preflight import missing_prerequisites, parse_env_file, x_handles


def test_configured_x_accounts_without_token_is_missing() -> None:
    # The whole point of B.2: a non-empty X list makes BRIGHT_DATA_KEY mandatory.
    missing = missing_prerequisites(
        config_exists=True,
        client_exists=True,
        x_accounts=["@anthropicai"],
        bright_data_key=None,
    )

    assert any("BRIGHT_DATA_KEY" in item for item in missing)


def test_missing_config_and_client_are_reported() -> None:
    # The existing Slice A prerequisites still hold and are named in the result.
    missing = missing_prerequisites(
        config_exists=False,
        client_exists=False,
        x_accounts=[],
        bright_data_key=None,
    )

    assert any("config.json" in item for item in missing)
    assert any("oauth_client.json" in item for item in missing)


def test_x_off_needs_no_token() -> None:
    # Opt-out: with no X accounts the pipeline runs exactly as Slice A — a
    # missing BRIGHT_DATA_KEY is not a prerequisite at all.
    missing = missing_prerequisites(
        config_exists=True,
        client_exists=True,
        x_accounts=[],
        bright_data_key=None,
    )

    assert missing == []


def test_x_handles_reads_the_x_list() -> None:
    assert x_handles({"x": ["@anthropicai", "@openaidevs"]}) == [
        "@anthropicai",
        "@openaidevs",
    ]


def test_x_handles_defaults_empty_when_absent_or_null() -> None:
    # accounts.json ships empty by default; an absent or null x key, or no file
    # at all (None), all mean "no X accounts" — never an error.
    assert x_handles({}) == []
    assert x_handles({"x": None}) == []
    assert x_handles(None) == []


def test_parse_env_file_reads_key_values_ignoring_noise() -> None:
    # Minimal .env support: KEY=value lines, blanks and # comments skipped,
    # surrounding whitespace and matching quotes stripped from the value.
    text = "\n".join(
        [
            "# secrets",
            "",
            "BRIGHT_DATA_KEY=bd-123",
            'APIFY_KEY = "ap-456"  ',
        ]
    )

    assert parse_env_file(text) == {
        "BRIGHT_DATA_KEY": "bd-123",
        "APIFY_KEY": "ap-456",
    }


def test_x_on_with_token_is_ready() -> None:
    # Opt-in satisfied: X accounts plus a token clears pre-flight.
    missing = missing_prerequisites(
        config_exists=True,
        client_exists=True,
        x_accounts=["@anthropicai"],
        bright_data_key="bd-secret",
    )

    assert missing == []
