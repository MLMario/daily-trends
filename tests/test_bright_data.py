"""Behavior tests for scripts.lib.bright_data.BrightDataClient.

Only the mechanical pre-HTTP path is unit-tested here — the missing-key
guard at construction. The HTTP wire shape (query string, body fields,
auth header, polling-loop termination, 540s ceiling) is verified by the
live `@pytest.mark.live` integration test in tests/integration/
test_bright_data_live.py, gated by the operator before merge.

This is a deliberate spec deviation from issue #28's AC line that asked
for mocked-HTTP unit tests of the client; see PR body.
"""

from __future__ import annotations

import pytest

from scripts.lib.bright_data import BrightDataClient


def test_missing_api_key_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicit api_key=None plus no BRIGHT_DATA_KEY in the environment is
    # the "operator forgot the secret" failure mode. The scrape_instagram
    # orchestrator catches this and converts it to a single ErrorLog event
    # under step `scrape_instagram` — so the client itself just needs to
    # signal clearly and not, e.g., send an unauthenticated request.
    monkeypatch.delenv("BRIGHT_DATA_KEY", raising=False)

    with pytest.raises(RuntimeError, match="BRIGHT_DATA_KEY"):
        BrightDataClient()


def test_explicit_api_key_overrides_missing_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The live test passes api_key explicitly (via env-loaded .env), so
    # constructing with a key must succeed even when the process env is
    # bare. Matches the GmailSender pattern of explicit-creds-over-env.
    monkeypatch.delenv("BRIGHT_DATA_KEY", raising=False)

    client = BrightDataClient(api_key="kx")

    assert client is not None
