"""Pre-flight prerequisite decisions for a run.

Pure helpers behind init_run's thin shell. The gating rule that defines Slice B:
BRIGHT_DATA_KEY is required iff `creators/accounts.json[x]` is non-empty — so the
news+vendor pipeline runs with no new credentials, and the token becomes
mandatory exactly when X is opted in.
"""

from __future__ import annotations

from collections.abc import Sequence


def parse_env_file(text: str) -> dict[str, str]:
    """Parse a minimal `.env`: ``KEY=value`` lines into a dict.

    Blank lines and ``#`` comments are skipped; whitespace around the key and
    value is trimmed; a single layer of matching surrounding quotes is stripped
    from the value. Enough for this repo's flat secrets file — not a full dotenv.
    """
    env: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def x_handles(accounts: dict | None) -> list[str]:
    """The configured X handles from parsed `creators/accounts.json`.

    Absent file (``None``), missing `x` key, or a null/empty value all resolve
    to ``[]`` — X is opt-in and silence means off.
    """
    if not accounts:
        return []
    return list(accounts.get("x") or [])


def missing_prerequisites(
    *,
    config_exists: bool,
    client_exists: bool,
    x_accounts: Sequence[str],
    bright_data_key: str | None,
) -> list[str]:
    """Names of unmet prerequisites, in pipeline order; empty means ready.

    BRIGHT_DATA_KEY is demanded only when `x_accounts` is non-empty.
    """
    missing: list[str] = []
    if not config_exists:
        missing.append("config.json")
    if not client_exists:
        missing.append("credentials/oauth_client.json")
    if x_accounts and not bright_data_key:
        missing.append(
            "BRIGHT_DATA_KEY (required when creators/accounts.json[x] is non-empty)"
        )
    return missing
