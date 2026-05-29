"""Behavior tests for scripts.transcribe_reels.transcribe_reels.

The helper takes paths + an injectable `model_factory` so each scenario
can vary the Whisper surface without importing `faster_whisper` (which
would require CUDA + the four nvidia/* wheels on the test runner).
Mirrors `scrape_instagram.scrape_instagram`'s testable-seam pattern.

`WhisperModel` is mocked everywhere here — production-quality Whisper
output is verified manually post-merge against `_tmp/slice-b-feasibility/`
fixtures (issue #29 AC line "no automated assertion").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from scripts.lib.run_workspace import RunWorkspace
from scripts.transcribe_reels import _prepend_nvidia_dll_dirs, transcribe_reels


# --- test doubles -----------------------------------------------------------


@dataclass
class FakeSegment:
    text: str


@dataclass
class FakeInfo:
    language: str = "en"
    duration: float = 0.0


@dataclass
class FakeModel:
    """Stand-in for faster_whisper.WhisperModel.

    Tests configure `device` (drives the CPU-fallback hard-fail branch),
    `transcribe_returns` (a list of `(segments, info)` tuples consumed in
    call order), and inspect `transcribe_calls` afterwards.
    """

    device: str = "cuda"
    transcribe_returns: list[tuple[list[FakeSegment], FakeInfo]] = field(
        default_factory=list
    )
    transcribe_calls: list[dict[str, Any]] = field(default_factory=list)

    # Mirror the faster_whisper layout: `.model.device` is the real device.
    @property
    def model(self) -> "FakeModel":
        return self

    def transcribe(
        self,
        audio: str,
        *,
        task: str = "transcribe",
        language: str | None = None,
    ) -> tuple[list[FakeSegment], FakeInfo]:
        self.transcribe_calls.append(
            {"audio": audio, "task": task, "language": language}
        )
        idx = min(len(self.transcribe_calls) - 1, len(self.transcribe_returns) - 1)
        if isinstance(self.transcribe_returns[idx], Exception):
            raise self.transcribe_returns[idx]
        return self.transcribe_returns[idx]


# --- fixtures ---------------------------------------------------------------


def _setup_workspace(tmp_path: Path) -> tuple[RunWorkspace, Path]:
    """Mint a fresh workspace with the IG subtree. Returns (workspace, runs_root)."""
    runs_root = tmp_path / "runs"
    workspace = RunWorkspace.new_run(runs_root, enable_instagram=True)
    return workspace, runs_root


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


# --- tests ------------------------------------------------------------------


def test_no_mp4_files_is_a_clean_no_op(tmp_path: Path) -> None:
    # Empty IG tree (e.g. quiet creator week): the helper walks the tree,
    # finds nothing, and exits without touching the model factory or
    # writing any log entries.
    workspace, runs_root = _setup_workspace(tmp_path)

    def factory_must_not_be_called() -> Any:
        raise AssertionError("model_factory should not be invoked with no .mp4 files")

    transcribe_reels(
        workspace.run_id,
        runs_root=runs_root,
        model_factory=factory_must_not_be_called,
    )

    assert _read_log(workspace.errors) == []


def test_dll_path_prep_on_win32_prepends_nvidia_bin_dirs_and_returns_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR-0003: on Windows the helper must (a) call os.add_dll_directory
    # for each nvidia/{cublas,cudnn,cuda_nvrtc}/bin and (b) prepend each
    # to PATH — add_dll_directory alone doesn't reach CT2's transitive
    # loads. The helper returns the prepended dirs (for logging).
    #
    # The test mints a synthetic venv layout under tmp_path mirroring
    # `<venv>/Scripts/python.exe` and `<venv>/Lib/site-packages/nvidia/*/bin`,
    # then patches sys.platform and sys.executable so the helper points
    # at the synthetic tree instead of the real venv on the test runner.
    import os

    venv = tmp_path / ".venv"
    site_pkgs = venv / "Lib" / "site-packages"
    expected_dirs = []
    for pkg in ("cublas", "cudnn", "cuda_nvrtc"):
        bin_dir = site_pkgs / "nvidia" / pkg / "bin"
        bin_dir.mkdir(parents=True)
        expected_dirs.append(str(bin_dir))

    fake_python = venv / "Scripts" / "python.exe"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("", encoding="utf-8")

    monkeypatch.setattr("scripts.transcribe_reels.sys.platform", "win32")
    monkeypatch.setattr("scripts.transcribe_reels.sys.executable", str(fake_python))

    # Track add_dll_directory calls so we know the OS-level registration
    # happened, not just the PATH prepend. os.add_dll_directory only
    # exists on Windows in real CPython; on this test runner it may or
    # may not — patch it unconditionally with a recording stub.
    add_calls: list[str] = []
    monkeypatch.setattr(
        "scripts.transcribe_reels.os.add_dll_directory",
        lambda p: add_calls.append(p) or None,
        raising=False,
    )

    baseline = "C:\\Windows\\System32"
    monkeypatch.setenv("PATH", baseline)

    added = _prepend_nvidia_dll_dirs()

    assert added == expected_dirs
    assert add_calls == expected_dirs
    # PATH is prefixed with the three bin dirs in order, followed by the
    # original PATH (separated by os.pathsep).
    assert os.environ["PATH"] == os.pathsep.join(expected_dirs + [baseline])


def test_dll_path_prep_is_a_no_op_on_non_win32(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADR-0003 codifies the Windows-specific PATH prepend + add_dll_directory
    # dance. On non-Windows platforms the helper must no-op cleanly — it
    # neither touches PATH nor raises — so that the same module imports
    # successfully on Linux CI (where the four nvidia/* wheels still exist
    # but CT2 does its own thing).
    monkeypatch.setattr("scripts.transcribe_reels.sys.platform", "linux")
    original_path = "/usr/bin:/usr/local/bin"
    monkeypatch.setenv("PATH", original_path)

    added = _prepend_nvidia_dll_dirs()

    assert added == []
    import os

    assert os.environ["PATH"] == original_path
