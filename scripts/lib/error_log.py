"""Append-only JSON-lines error/event log.

Schema per line: {step, severity, message, timestamp, item_id?, kind?}.

`summary()` rolls the raw log up for the email's Errors & Skips section. It
groups entries by `step` in **first-seen order** (the order each step first
appears in the log — i.e. pipeline order — not alphabetical), so the email
reads top-to-bottom the way the run unfolded. Per group it counts `error` and
`warning` entries and collects consequential-info rows (`severity:"info"` with
`kind:"consequential"`). Pure-info entries — info without the consequential
kind, e.g. the stage-boundary timing markers — are excluded from the summary
but remain in the raw log. A step that produced only pure info forms no group,
so an empty or info-only log summarizes as empty.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class StepGroup:
    step: str
    error_count: int
    warning_count: int
    consequential: tuple[str, ...]


@dataclass(frozen=True)
class ErrorSummary:
    groups: tuple[StepGroup, ...]

    @property
    def is_empty(self) -> bool:
        return not self.groups


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

    def summary(self) -> ErrorSummary:
        if not self._path.exists():
            return ErrorSummary(groups=())

        errors: dict[str, int] = {}
        warnings: dict[str, int] = {}
        consequential: dict[str, list[str]] = {}
        order: list[str] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            entry = json.loads(line)
            step = entry["step"]
            if step not in order:
                order.append(step)
                errors[step] = 0
                warnings[step] = 0
                consequential[step] = []
            severity = entry.get("severity")
            if severity == "error":
                errors[step] += 1
            elif severity == "warning":
                warnings[step] += 1
            elif severity == "info" and entry.get("kind") == "consequential":
                consequential[step].append(entry.get("message", ""))

        groups = tuple(
            StepGroup(
                step=step,
                error_count=errors[step],
                warning_count=warnings[step],
                consequential=tuple(consequential[step]),
            )
            for step in order
            if errors[step] or warnings[step] or consequential[step]
        )
        return ErrorSummary(groups=groups)
