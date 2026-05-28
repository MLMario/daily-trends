# ADR 0003 — Local Whisper runtime for Slice B transcription

**Status:** accepted (2026-05-28). `faster-whisper 1.2.1` + `ctranslate2 4.7.2` on GPU with `compute_type="float16"` confirmed working end-to-end against the existing `@hellovidya` fixture from ADR-0002. Slice B step 2 proceeds as designed, with one refinement to the quantization choice and one runtime constraint (Windows DLL path) for `scripts/transcribe_reels.py` to honor.

## Decision

Slice B step 2 (Reel `.mp4` → `<post_id>.transcript.json`) uses `faster-whisper` (small model, multilingual) with `compute_type="float16"` on the operator's local NVIDIA RTX 5070 Ti. The library choice and model size from `process_design.md` are confirmed; the quantization line `int8` is refined to **`float16` on GPU; `int8` fallback on CPU only**.

Rationale, in one sentence: the box is a Blackwell sm_120 GPU and CTranslate2 4.6.2 (2025-12-05) explicitly disabled INT8 codepaths on sm_120 because the Blackwell tensor cores need an INT8 padding scheme upstream hasn't implemented — so `int8` either silently degrades or trips `cuBLAS CUBLAS_STATUS_NOT_SUPPORTED`. `float16` keeps the CTranslate2 backend, runs natively on this GPU at ~5.5 s warm-cache per ~3 min Reel, and costs only ~1.3 GB of the available 16 GB VRAM.

## Context

`process_design.md` §4 step 2 (line 110), §6 capability map (line 206), and §9 open question (line 371) commit Slice B to `faster-whisper (small, int8)` but left the hardware path explicitly open. Two assumptions were load-bearing before `scripts/transcribe_reels.py` could be built:

1. The Whisper ecosystem supports RTX 50-series Blackwell + CUDA 13.1 driver on Windows 11 today — not just on paper but with installable wheels.
2. The locked `int8` quantization actually runs on this specific GPU.

A research sweep (`_tmp/slice-b-whisper-research/RESEARCH.md`, 16 cited sources) surfaced the Blackwell INT8 disablement and the cuDNN/cuBLAS DLL search behavior on Windows. A feasibility smoke test (`_tmp/slice-b-whisper-feasibility/`) then verified the proposed path against the `.mp4` fixture from ADR-0002 (`3906868330239713824_51994227.mp4`, 172 s English, `@hellovidya`).

## Investigation (2026-05-28)

Single-option feasibility test on the RTX 5070 Ti (Blackwell, sm_120, 16 GB VRAM, CUDA 13.1 driver) + Intel Core Ultra 7 265K + 63 GB RAM + Windows 11. Tooling: `uv` only. Code under `_tmp/slice-b-whisper-feasibility/` (gitignored, not committed).

### Stage outcomes

| Stage | Outcome | Evidence |
|---|---|---|
| 1. Install dev-deps via `uv add --dev` | ✅ 30 packages resolved. Pins: `faster-whisper==1.2.1`, `ctranslate2==4.7.2` (≥ the 4.6.3 floor that lifted sm_120 INT8 disablement plus added CUDA 12.8 support), `nvidia-cublas-cu12==12.9.2.10`, `nvidia-cudnn-cu12==9.22.0.52` (CT2 ≥ 4.5.0 needs cuDNN 9.x). | `pyproject.toml` dev group, `uv.lock` |
| 2. Model download (first call) | ✅ `small` weights landed at `_tmp/slice-b-whisper-feasibility/models/models--Systran--faster-whisper-small/` at **464 MB**, matching the ~461 MB estimate from research. | `du -sh` |
| 3. Pass 1 transcribe (cold) | ✅ Wall-clock **12.6 s** for 172 s audio. Includes first-call model load + initial CUDA-context warm-up. | `run.log` line 1 |
| 3'. Pass 1 transcribe (warm) | ✅ Wall-clock **5.5 s** for 172 s audio — this is the steady-state daily-pipeline cost. Language `en` at probability 1.0; 77 segments; reported duration 171.759 s (matches the fixture). | `run.log` (rerun) |
| 4. Output schema | ✅ Transcript JSON contains exactly `{text, language, duration_sec}` for the English fixture. `text_en` correctly absent (pass 2 skipped). Schema `assert` in `smoke_test.py` honored. | `3906868330239713824.transcript.json` |
| 5. VRAM | ✅ Idle baseline 2.7 GB / 16 GB (desktop apps); model adds ~1.3 GB peak per research §5 — far inside the 16 GB budget. Sampled via `nvidia-smi`. | Manual sample |
| (Footgun) | ⚠️ First run failed with `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`. Root cause: `os.add_dll_directory()` alone does not reach CTranslate2's transitive DLL loads on Windows. Resolution: also prepend the wheel-installed `nvidia/{cublas,cudnn,cuda_nvrtc}/bin/` directories to `PATH` *before* importing `faster_whisper`. Worked deterministically on retry. | `smoke_test.py::_prepend_nvidia_dll_dirs` |

### Confirmed runtime characteristics

- **Per-Reel cost (steady state):** ~5.5 s GPU on ~3 min audio. For the design's batch of 5 Reels/day this means ~28 s total transcription budget — negligible inside the daily pipeline.
- **First-call cost:** +7 s for CUDA-context warm-up. The daily pipeline should be expected to pay this once per run.
- **VRAM ceiling:** ~1.3 GB peak for `small`/fp16 — leaves ~13 GB headroom against the 16 GB cap, so a future slice can host a heavier model concurrently if needed.
- **Disk:** 464 MB for the `small` weights. Recommended cache location: `models/whisper/` at the repo root (gitignored), set via `download_root=` kwarg on `WhisperModel(...)` so the cache is co-located and easy to delete.
- **Audio I/O:** `faster-whisper` reads the `.mp4` directly via PyAV-bundled ffmpeg. No system `ffmpeg.exe` install required on Windows.
- **Transcript quality (spot-check):** 172 s `@hellovidya` Reel about LinkedIn product leaders and AI-written-post crackdown transcribed coherently with domain terms intact ("VPs of product", "AI written posts", "final layer"). Zero visible hallucinations. One cosmetic artifact: double-spaces between segments from `" ".join(segment.text)` — each segment ends in a trailing space; collapsing whitespace at corpus-normalization time is the right fix, not a transcription change.

## `task="translate"` semantics (confirmed two-pass)

`faster-whisper`'s `transcribe(audio, language=None, task="transcribe", ...)` with `task="translate"` returns **English only** — the original-language transcript is not co-produced. To populate the design's `{text, text_en?}` schema for a non-English Reel, the implementation runs `transcribe` twice:

```python
# Pass 1: native transcript + language detection
segments, info = model.transcribe(audio, task="transcribe")
text = " ".join(s.text for s in segments)
language = info.language

# Pass 2 (only if language != "en"): English translation
text_en = None
if language != "en":
    segments_en, _ = model.transcribe(audio, task="translate", language=language)
    text_en = " ".join(s.text for s in segments_en)
```

Cost: 2× model invocations on a non-English Reel — ~11 s GPU instead of ~5.5 s. Acceptable given the corpus is English-dominant (most Reels skip pass 2). This two-pass path was **not exercised** during the feasibility test (the operator declined the stretch goal of fetching a non-English fixture). It will be exercised on the first organic non-English Reel that lands in production; if the design wants earlier verification, capture as a Slice B.4 sub-task.

## Consequences

Slice B step 2 build can proceed as `scripts/transcribe_reels.py`. Concrete constraints the implementation MUST honor:

- **Windows DLL search path.** On import, prepend `<venv>/Lib/site-packages/nvidia/{cublas,cudnn,cuda_nvrtc}/bin/` to `os.environ["PATH"]` AND call `os.add_dll_directory(...)` for each. `os.add_dll_directory()` alone is insufficient on Windows for CT2's transitive DLL loads. Pattern documented in `_tmp/slice-b-whisper-feasibility/smoke_test.py::_prepend_nvidia_dll_dirs` — copy-paste into the production script.
- **`compute_type="float16"` is mandatory on GPU.** Do not pass `int8` or `int8_float16` while running on this hardware. If the CT2 release notes ever announce sm_120 INT8 re-enablement (track issues `OpenNMT/CTranslate2#1937` and `#1982`), revisit. Captured as a `gsd:plant-seed` (see below).
- **Hard-fail on silent CPU fallback.** Production script must inspect `model.model.device` after construction and raise if the device is not `cuda` when GPU was requested — masking a CPU fallback as "successful" makes the daily pipeline silently 6× slower (RESEARCH §5: ~12-15 s CPU vs ~5.5 s GPU on this hardware).
- **Two-pass `task="translate"` is the contract.** Always run `task="transcribe"` first, then conditionally `task="translate"` when `info.language != "en"`. Do not use `task="translate"` in pass 1 — it returns English only and destroys the native transcript.
- **Try/except + `ErrorLog`.** Per-Reel transcription wrapped in try/except; failures log to `runs/<run_id>/errors.log` via `scripts/lib/error_log.py` with `step="transcribe_reels"`, `severity="warning"`, `item_id="<post_id>"`. Skip on failure; do not retry. Matches the design's "no silent failures" contract.
- **Model cache location.** Pass `download_root="models/whisper"` to `WhisperModel(...)`. Add `models/` to `.gitignore` if not already covered. Default Hugging Face cache (`~/.cache/huggingface/`) is left alone.
- **Promote dev-deps to runtime when Slice B.4 lands.** The four packages (`faster-whisper`, `ctranslate2`, `nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) currently sit in `[dependency-groups].dev`. They move to runtime `dependencies` in the same commit set that lands `scripts/transcribe_reels.py`. Mirrors how `yt-dlp` will graduate from dev (ADR-0002) to runtime when Slice B.3 lands.

### Refinement to `process_design.md`

§4 step 2 (line 110), §6 capability map (line 206), §9 open question (line 371) get a small targeted edit:

- §4 step 2 Capabilities column: `faster-whisper (small, int8)` → `faster-whisper (small, float16 on GPU)`. Add pointer to this ADR in the Awareness Check column.
- §6 capability map row: `faster-whisper (small, int8) in Python` → `faster-whisper (small, float16 on GPU; int8 CPU fallback) in Python`.
- §9 "Whisper hardware path" open question: strikethrough and move to the "Resolved" block with pointer to this ADR. Conclusion: GPU on the operator's RTX 5070 Ti via `float16`.

These three edits land in one commit immediately after this ADR.

## When this ADR would be re-evaluated

- **CTranslate2 re-enables INT8 on sm_120.** `float16` doubles VRAM vs. `int8` (~1.3 GB vs ~0.7 GB est.). At the current 5-Reels/day batch this is irrelevant, but if the pipeline ever runs Whisper concurrently with a heavier model, `int8` becomes the right pick. Track upstream issues `OpenNMT/CTranslate2#1937` (Blackwell INT8 disablement) and `#1982` (CUDA 12.8 support). Captured separately as a `gsd:plant-seed`.
- **Daily pipeline outgrows 5 Reels.** If the batch grows past ~50 Reels/day or longer-form content (~10 min) enters the mix, reconsider `small` → `base` or warm-cache strategies (process pool, model preload).
- **GPU changes.** If the operator's hardware changes off Blackwell (or to a non-NVIDIA accelerator), revisit the `compute_type` and `device` choices. The library and model decisions likely survive a GPU swap.
- **Translation-quality complaint surfaces.** If non-English Reels translate poorly (Whisper's translate task is not state-of-the-art for ES/PT → EN), bolt on a dedicated translation step (e.g. NLLB) after pass 1 rather than relying on `task="translate"`.

## Considered alternatives

Full comparison in `_tmp/slice-b-whisper-research/RESEARCH.md` §3. One-line rationale for each rejected option:

- **`faster-whisper` `small` `int8` (the design's original line)** — falsified for this GPU by CT2 4.6.2 Blackwell disablement. The library and model are still correct; only the quantization changes.
- **`pywhispercpp` (whisper.cpp Python bindings) with CUDA build** — viable Plan B that sidesteps the CT2/PyTorch wheel ecosystem entirely. Trade-off: requires system `ffmpeg.exe` on PATH and a C++/CUDA toolchain to build the CUDA variant. Reject because the recommended path works and is one `uv add` line.
- **`openai-whisper` (reference PyTorch)** — stable PyTorch 2.7/2.8/2.9 ship no sm_120 wheels as of May 2026; nightly `cu128`/`cu129` have intermittent missing-cuDNN failures on Windows. Reject as not viable today on this box.
- **`whisperx`** — adds wav2vec2 alignment + pyannote diarization the daily-trends use case doesn't need, and Blackwell install is unresolved (`m-bain/whisperX#1211`). Reject as both broken and overkill.
- **Purfview's `whisper-standalone-win`** — bundles known-good DLLs and works as a subprocess invocation. Useful as an escape hatch if the cuDNN pip wheels ever misbehave, but breaks the "pure Python via uv" project model. Hold in reserve, do not adopt.

## Captured for later (do not action this slice)

- `gsd:plant-seed`: "When CTranslate2 re-enables INT8 on sm_120, revisit fp16 → int8 to halve VRAM. Track issues `OpenNMT/CTranslate2#1937` and `#1982`." Trigger: any new CT2 release notes mentioning Blackwell or sm_120 INT8.
- Optional Slice B.4 sub-task: exercise the pass-2 `task="translate"` code path on the first organic non-English Reel that lands, or on a synthetic ES/PT fixture if the operator wants earlier verification.
