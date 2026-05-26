"""Append-only JSON-lines error/event log.

Schema per line: {step, severity, message, timestamp, item_id?, kind?}.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning", "info"]


class ErrorLog:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def log(
        self,
        *,
        step: str,
        severity: Severity,
        message: str,
        item_id: str | None = None,
        kind: str | None = None,
    ) -> None:
        entry: dict[str, object] = {
            "step": step,
            "severity": severity,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if item_id is not None:
            entry["item_id"] = item_id
        if kind is not None:
            entry["kind"] = kind
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
