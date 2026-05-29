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

import os
import sys
from pathlib import Path
from typing import Callable

from scripts.lib.error_log import ErrorLog
from scripts.lib.run_workspace import RunWorkspace

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
