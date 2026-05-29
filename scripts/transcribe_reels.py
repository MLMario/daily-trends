"""Per-run Whisper transcription of the Instagram Reels Slice B.3 lands.

Discovers `.mp4` files under `runs/<run_id>/instagram/<account>/`, runs
`faster-whisper small` at `float16` on CUDA, and writes per-Reel
`<post_id>.transcript.json` keyed to the ADR-0003 schema:
`{text, text_en?, language, duration_sec}`. The IG corpus reader (B.1)
then picks them up at corpus-normalize time.

Production runtime constraints honored (all from ADR-0003):
  - Windows DLL search-path prep before importing `faster_whisper`
  - `compute_type="float16"` is mandatory on this GPU
  - `model.model.device != "cuda"` hard-fails (no silent CPU fallback)
  - Two-pass `task="transcribe"` then conditional `task="translate"`
    when `info.language != "en"`
  - Per-Reel try/except: failures log `warning` with `item_id=<post_id>`
    and skip; model-load failure logs `error` and exits 0.

Mirrors `scrape_instagram`'s testable-seam pattern: `transcribe_reels(...)`
takes paths + an injectable `model_factory` so tests pass a `FakeModel`
without importing `faster_whisper`; `main()` wires the production
constants, runs the Windows DLL prep, and builds the real
`WhisperModel` inside the factory closure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = REPO_ROOT / "runs"
MODEL_CACHE = REPO_ROOT / "models" / "whisper"

STEP = "transcribe_reels"


def _prepend_nvidia_dll_dirs() -> list[str]:
    """On Windows, prep CTranslate2's DLL search path before importing
    `faster_whisper`.

    `os.add_dll_directory()` alone is insufficient for CT2's transitive
    DLL loads on Windows — the wheel-installed
    `<venv>/Lib/site-packages/nvidia/{cublas,cudnn,cuda_nvrtc}/bin/`
    directories must also be on `PATH`. Pattern verified in the Slice B
    feasibility smoke (`_tmp/slice-b-whisper-feasibility/smoke_test.py`)
    and codified in ADR-0003.

    On non-Windows platforms this is a deliberate no-op — the helper
    returns `[]` and leaves `PATH` untouched, so the module imports
    cleanly on Linux/macOS even though the production runtime is
    Windows-only.

    Returns the list of bin directories prepended, for logging.
    """
    if sys.platform != "win32":
        return []
    # sys.executable is `<venv>/Scripts/python.exe` on Windows venvs;
    # `.parent.parent` resolves to the venv root.
    venv = Path(sys.executable).parent.parent
    site_pkgs = venv / "Lib" / "site-packages"
    added: list[str] = []
    for pkg in ("cublas", "cudnn", "cuda_nvrtc"):
        bin_dir = site_pkgs / "nvidia" / pkg / "bin"
        if bin_dir.is_dir():
            os.add_dll_directory(str(bin_dir))
            added.append(str(bin_dir))
    if added:
        os.environ["PATH"] = os.pathsep.join(
            added + [os.environ.get("PATH", "")]
        )
    return added


def transcribe_reels(
    run_id: str,
    *,
    runs_root: Path,
    model_factory: Callable[[], object] | None = None,
    log: ErrorLog | None = None,
) -> None:
    """Run the transcribe step against an already-minted run.

    No-ops cleanly when no `.mp4` files exist under the run's IG tree
    (quiet creator week, or B.3 short-circuited on an empty list).
    """
    workspace = RunWorkspace.existing_run(runs_root, run_id)
    log = log or ErrorLog(workspace.errors)

    mp4_paths = sorted((workspace.path / "instagram").glob("*/*.mp4"))
    if not mp4_paths:
        return

    if model_factory is None:  # pragma: no cover — production wires the real one
        raise RuntimeError("transcribe_reels requires a model_factory")

    try:
        model = model_factory()
    except Exception as exc:  # noqa: BLE001 — taxonomy maps any load failure to one event
        log.log(step=STEP, severity="error", message=str(exc))
        return

    # ADR-0003 hard-fail: a silent CPU fallback (CUDA driver missing,
    # cuBLAS misload, GPU OOM at construction) makes the daily pipeline
    # ~6× slower without the operator ever finding out. Refuse to run.
    device = str(getattr(getattr(model, "model", None), "device", "")).lower()
    if device != "cuda":
        log.log(
            step=STEP,
            severity="error",
            message=f"expected device=cuda, got {device!r} — refusing silent CPU fallback",
        )
        return

    for mp4_path in mp4_paths:
        account = mp4_path.parent.name
        post_id = mp4_path.stem
        transcript_path = workspace.instagram_transcript(account, post_id)
        # US #21: re-running on the same run_id is idempotent — already-
        # transcribed Reels are skipped so GPU time isn't burned twice.
        if transcript_path.exists():
            continue
        try:
            _transcribe_one(
                model,
                audio=mp4_path,
                transcript_path=transcript_path,
            )
        except Exception as exc:  # noqa: BLE001 — per-Reel try/except per ADR-0003
            # Deviation #2 from the handoff: don't write a half-baked
            # transcript on failure. No file at all → the normalizer
            # drops the Reel for missing-transcript, not empty-text.
            if transcript_path.exists():
                transcript_path.unlink()
            log.log(
                step=STEP,
                severity="warning",
                message=str(exc),
                item_id=post_id,
            )


def _transcribe_one(
    model: Any,
    *,
    audio: Path,
    transcript_path: Path,
) -> None:
    """Run two-pass Whisper on a single Reel and write the transcript.

    Pass 1 (`task="transcribe"`) always runs and produces the native
    transcript + detected language. Pass 2 (`task="translate"`) runs
    only when `info.language != "en"` and produces the English
    translation written under `text_en`.
    """
    segments, info = model.transcribe(str(audio), task="transcribe")
    text = " ".join(s.text for s in segments).strip()
    payload: dict[str, Any] = {
        "text": text,
        "language": info.language,
        "duration_sec": round(info.duration, 3),
    }
    if info.language != "en":
        # Two-pass per ADR-0003: pass 2 = English translation. The
        # corpus normalizer reads `text_en or text`, so this is what
        # the clustering subagent sees for non-English Reels.
        segments_en, _ = model.transcribe(
            str(audio), task="translate", language=info.language
        )
        payload["text_en"] = " ".join(s.text for s in segments_en).strip()
    transcript_path.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _build_real_whisper_factory() -> Callable[[], object]:
    """Production factory: deferred import of `faster_whisper` (must come
    after `_prepend_nvidia_dll_dirs()` on Windows) + `WhisperModel`
    constructor pinned to the ADR-0003 line.

    Returned closure is the `model_factory` `transcribe_reels` invokes.
    Any constructor failure (CUDA driver missing, model download fails,
    etc.) bubbles up through the closure into the helper's load-failure
    catch site.
    """

    def _factory() -> object:
        from faster_whisper import WhisperModel  # noqa: PLC0415 — deferred per ADR-0003

        return WhisperModel(
            "small",
            device="cuda",
            compute_type="float16",
            download_root=str(MODEL_CACHE),
        )

    return _factory


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: transcribe_reels.py <run_id>", file=sys.stderr)
        return 2
    run_id = args[0]

    # MUST run before the factory closure imports faster_whisper. The
    # helper itself is a no-op on non-Windows; on Windows it prepends
    # nvidia/{cublas,cudnn,cuda_nvrtc}/bin to PATH and registers each
    # via os.add_dll_directory so CT2's transitive DLL loads succeed.
    _prepend_nvidia_dll_dirs()

    transcribe_reels(
        run_id,
        runs_root=RUNS_ROOT,
        model_factory=_build_real_whisper_factory(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
