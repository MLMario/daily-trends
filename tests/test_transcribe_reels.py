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


def test_non_english_reel_runs_two_pass_writes_text_and_text_en(
    tmp_path: Path,
) -> None:
    # ADR-0003 two-pass contract for a non-English Reel:
    # pass 1 — task="transcribe" → native transcript + detected language
    # pass 2 — task="translate", language=info.language → English text
    # The output schema gains `text_en` alongside `text`. The corpus
    # normalizer (B.1) prefers `text_en` for non-English Reels — locked
    # by tests in test_corpus_normalizer.
    workspace, runs_root = _setup_workspace(tmp_path)
    account_dir = workspace.instagram_dir("hellovidya")
    account_dir.mkdir(parents=True)
    (account_dir / "pES.mp4").write_bytes(b"fake mp4")

    model = FakeModel(
        transcribe_returns=[
            (
                [FakeSegment(text="Hola "), FakeSegment(text="mundo.")],
                FakeInfo(language="es", duration=18.0),
            ),
            (
                [FakeSegment(text="Hello "), FakeSegment(text="world.")],
                FakeInfo(language="es", duration=18.0),
            ),
        ],
    )
    transcribe_reels(
        workspace.run_id,
        runs_root=runs_root,
        model_factory=lambda: model,
    )

    assert len(model.transcribe_calls) == 2
    p1, p2 = model.transcribe_calls
    assert p1["task"] == "transcribe"
    assert p1["language"] is None
    assert p2["task"] == "translate"
    assert p2["language"] == "es"  # info.language from pass 1

    payload = json.loads(
        workspace.instagram_transcript("hellovidya", "pES").read_text(encoding="utf-8")
    )
    assert payload["text"] == "Hola  mundo."
    assert payload["text_en"] == "Hello  world."
    assert payload["language"] == "es"
    assert payload["duration_sec"] == 18.0


def test_english_reel_runs_single_pass_writes_no_text_en(tmp_path: Path) -> None:
    # ADR-0003 two-pass contract for an English Reel: ONE transcribe call
    # (`task="transcribe"`), output keys exactly `{text, language,
    # duration_sec}` — `text_en` is absent. Segment text is concatenated
    # with a single space and stripped at the boundaries.
    workspace, runs_root = _setup_workspace(tmp_path)
    account_dir = workspace.instagram_dir("hellovidya")
    account_dir.mkdir(parents=True)
    (account_dir / "pA.mp4").write_bytes(b"fake mp4")

    model = FakeModel(
        transcribe_returns=[
            (
                [FakeSegment(text="Hello "), FakeSegment(text="world.")],
                FakeInfo(language="en", duration=42.555),
            ),
        ],
    )
    transcribe_reels(
        workspace.run_id,
        runs_root=runs_root,
        model_factory=lambda: model,
    )

    [call] = model.transcribe_calls
    assert call["task"] == "transcribe"

    payload = json.loads(
        workspace.instagram_transcript("hellovidya", "pA").read_text(encoding="utf-8")
    )
    assert set(payload.keys()) == {"text", "language", "duration_sec"}
    assert payload["text"] == "Hello  world."
    assert payload["language"] == "en"
    assert payload["duration_sec"] == 42.555


def test_skip_if_transcript_already_exists(tmp_path: Path) -> None:
    # US #21: re-running on the same run_id does not burn GPU time on
    # Reels that already have a `.transcript.json` on disk. The helper
    # skips them entirely — no model.transcribe(...) call, no overwrite.
    # The Reel that doesn't have a transcript yet still gets transcribed.
    workspace, runs_root = _setup_workspace(tmp_path)
    account_dir = workspace.instagram_dir("hellovidya")
    account_dir.mkdir(parents=True)
    (account_dir / "pA.mp4").write_bytes(b"fake mp4 A")
    (account_dir / "pB.mp4").write_bytes(b"fake mp4 B")

    # pA's transcript already exists from a prior run.
    existing = {"text": "cached", "language": "en", "duration_sec": 5.0}
    workspace.instagram_transcript("hellovidya", "pA").write_text(
        json.dumps(existing), encoding="utf-8"
    )

    model = FakeModel(
        transcribe_returns=[
            ([FakeSegment(text="new B")], FakeInfo(language="en", duration=12.0)),
        ],
    )
    transcribe_reels(
        workspace.run_id,
        runs_root=runs_root,
        model_factory=lambda: model,
    )

    # Only pB went through Whisper. pA's existing transcript is untouched.
    assert len(model.transcribe_calls) == 1
    assert Path(model.transcribe_calls[0]["audio"]).name == "pB.mp4"
    assert json.loads(
        workspace.instagram_transcript("hellovidya", "pA").read_text(encoding="utf-8")
    ) == existing


def test_discovery_walks_instagram_tree_and_transcribes_each_reel(
    tmp_path: Path,
) -> None:
    # Discovery walks runs/<run_id>/instagram/<account>/*.mp4 across all
    # accounts. Each .mp4 produces one model.transcribe(...) call (English
    # path — info.language == "en", so pass 2 is skipped) and one
    # <post_id>.transcript.json next to it. Schema correctness is asserted
    # downstream — this test pins the discovery walk and the per-Reel
    # round-trip.
    workspace, runs_root = _setup_workspace(tmp_path)

    for account, post_id in [("hellovidya", "pA"), ("anothercreator", "pB")]:
        d = workspace.instagram_dir(account)
        d.mkdir(parents=True)
        (d / f"{post_id}.mp4").write_bytes(b"fake mp4")

    model = FakeModel(
        transcribe_returns=[
            ([FakeSegment(text="hello A")], FakeInfo(language="en", duration=10.0)),
            ([FakeSegment(text="hello B")], FakeInfo(language="en", duration=20.0)),
        ],
    )

    transcribe_reels(
        workspace.run_id,
        runs_root=runs_root,
        model_factory=lambda: model,
    )

    # One transcribe call per .mp4 — sorted across accounts/post_ids.
    audio_args = [c["audio"] for c in model.transcribe_calls]
    assert workspace.instagram_mp4("anothercreator", "pB").as_posix() in [
        Path(a).as_posix() for a in audio_args
    ]
    assert workspace.instagram_mp4("hellovidya", "pA").as_posix() in [
        Path(a).as_posix() for a in audio_args
    ]
    assert len(model.transcribe_calls) == 2

    # Transcript files land at the typed paths.
    assert workspace.instagram_transcript("hellovidya", "pA").is_file()
    assert workspace.instagram_transcript("anothercreator", "pB").is_file()


def test_cpu_fallback_logs_error_and_skips_transcription(tmp_path: Path) -> None:
    # ADR-0003: silent CPU fallback masks the real failure (~6× slowdown
    # vs GPU on this hardware) — the helper inspects model.model.device
    # right after construction and treats a non-cuda value as `error`
    # step `transcribe_reels`. Process exits cleanly; no Reel is
    # transcribed; no transcript file lands.
    workspace, runs_root = _setup_workspace(tmp_path)
    account_dir = workspace.instagram_dir("hellovidya")
    account_dir.mkdir(parents=True)
    (account_dir / "p1.mp4").write_bytes(b"fake mp4")

    cpu_model = FakeModel(device="cpu")
    transcribe_reels(
        workspace.run_id,
        runs_root=runs_root,
        model_factory=lambda: cpu_model,
    )

    assert cpu_model.transcribe_calls == []
    entries = _read_log(workspace.errors)
    assert len(entries) == 1
    [entry] = entries
    assert entry["step"] == "transcribe_reels"
    assert entry["severity"] == "error"
    msg = entry["message"].lower()
    assert "cuda" in msg or "cpu" in msg
    assert not workspace.instagram_transcript("hellovidya", "p1").exists()


def test_model_factory_raising_logs_error_and_returns_cleanly(
    tmp_path: Path,
) -> None:
    # Per the issue #29 error taxonomy: "Whisper model load fails" →
    # severity=error, step=transcribe_reels, exit 0. In the helper
    # that translates to: catch the factory exception, log one error
    # entry, return. Don't bubble out — the pipeline continues; the
    # IG Reels all drop at normalize since no transcripts will exist.
    workspace, runs_root = _setup_workspace(tmp_path)
    account_dir = workspace.instagram_dir("hellovidya")
    account_dir.mkdir(parents=True)
    (account_dir / "p1.mp4").write_bytes(b"fake mp4")

    def boom() -> Any:
        raise RuntimeError("cuBLAS DLL load failed")

    transcribe_reels(
        workspace.run_id,
        runs_root=runs_root,
        model_factory=boom,
    )

    entries = _read_log(workspace.errors)
    assert len(entries) == 1
    [entry] = entries
    assert entry["step"] == "transcribe_reels"
    assert entry["severity"] == "error"
    assert "cuBLAS DLL load failed" in entry["message"]
    # No transcript should have landed for the Reel either.
    assert not workspace.instagram_transcript("hellovidya", "p1").exists()


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
