"""Pin the shape of the operator-facing config + creator-list files.

These files are the opt-in surface for the IG source — the rest of the
pipeline reads them but never writes them. Tests here protect against
accidental drift (e.g. a key rename in a future slice) without describing
internal implementation.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.json"
ACCOUNTS = REPO_ROOT / "creators" / "accounts.json"


def test_config_carries_instagram_lookback_and_post_count_defaults() -> None:
    # Slice B.2 plumbs the IG snapshot's two knobs into config.json so the
    # B.3 BrightDataClient can read them at trigger time. Defaults match the
    # parent PRD (#24): 7-day lookback, 5 most recent Reels per creator.
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    assert config["instagram_lookback_days"] == 7
    assert config["instagram_num_of_posts"] == 5


def test_accounts_seeds_hellovidya_and_preserves_empty_x_list() -> None:
    # Initial creator list: one IG handle (@hellovidya). The `x` key is
    # carried as an empty list to preserve the Slice C surface — the X
    # source is deferred but the schema stays stable so its later wiring
    # is purely additive.
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8"))

    assert accounts == {"instagram": ["hellovidya"], "x": []}
