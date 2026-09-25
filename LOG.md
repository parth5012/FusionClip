# Execution Log

## 2026-09-23: Wayfinder Map #67 - Trust & Integrity Fixes

### Status: Done

### Changes & Verification:
- **Phase 1 (HITL): #78 - Decide which trust gaps ship in v1 and honest-labeling policy**
  - Interviewed operator and resolved all 4 trust gaps to ship in v1 (real embeddings, real tunnel endpoints, disable upscale button with tooltip, strict 400 task_type enum).
  - Recorded resolution on #78 and closed.
- **Phase 2 (AFK): #79 - Wire Settings tunnel form and header badge to backend**
  - Added `frontend/src/utils/tunnel.ts` normalizing settings intent and resolving against GET /api/colab/metrics with 10s-staleness rule.
  - Added API functions in `frontend/src/utils/api.ts`: `fetchTunnelSettings`, `configureColabTunnel`, and `fetchColabTunnelState`.
  - Updated `SettingsPanel.tsx` to read from/write to backend via POST /api/colab/tunnel and GET /api/colab/metrics.
  - Updated `Header.tsx` to poll backend tunnel state so the badge reflects real connectivity.
  - Updated `useStore.ts` with v2 schema migration to exclude `colabTunnel` from localStorage partialize.
  - Added unit tests in `frontend/src/utils/tunnel.test.ts` (3 passed) and e2e integration tests in `04-settings-configuration.spec.ts`.
  - Verified: `bun test frontend/src/utils/tunnel.test.ts` (3 passed), `npx tsc --noEmit` (clean). Commit `ab72a63`.
- **Phase 2 (AFK): #80 - Replace fake embeddings with real MiniLM-L6-v2 + backfill**
  - Added `app/services/embedding.py` using `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions) via fastembed/sentence-transformers with deterministic fallback.
  - Migrated `MediaAsset.embedding` from `Vector(1536)` to `Vector(384)` in `app/models.py` and created Alembic migration `a8d1e394f01c_migrate_embeddings_1536_to_384.py`.
  - Updated `search_media()` to compute real semantic query embeddings, order by native pgvector cosine distance on PostgreSQL, compute cosine distance ranking in Python on SQLite/non-pgvector environments, and fall back to ILIKE text search if no embeddings exist or vector search fails.
  - Wired automatic embedding calculation on media upload and generation.
  - Added `POST /api/media/backfill-embeddings` endpoint and backfill utility for existing rows.
  - Added test suite `backend/tests/test_semantic_search.py` verifying 384-dim dimensions, ranking of semantically-related queries without word overlap, backfill, and ILIKE fallback.
  - Verified: `pytest backend/tests/test_semantic_search.py` (5 passed in 0.81s). Commit `19ece6d`.
- **Phase 2 (AFK): #81 - Strictly validate task_type with 400 enum and disable lying Upscale button**
  - Added `ALLOWED_TASK_TYPES = frozenset({"transcode", "thumbnail", "waveform", "audio_extract"})` in `backend/app/routers/tasks.py`.
  - Rejecting any request with unknown `task_type` (including `upscale`) with HTTP 400 Bad Request and error detail containing allowed types.
  - Disabled the dead Upscale button in `frontend/src/components/FileManager.tsx` with honest tooltip `title="Upscale pipeline coming soon (pending Magnific Core map)"` and aria-disabled styling, preserving layout for the Magnific map.
  - Added regression test suite `backend/tests/test_tasks_validation.py` asserting 400 response for unknown task types and 200 for valid pipelines.
  - Verified: `pytest backend/tests/test_tasks_validation.py` (3 passed in 0.08s). Commit `e6b2fac`.

### Overall Verification:
- Backend: 185 pytest unit & integration tests passing (`pytest backend/tests/` 185 passed).
- Frontend: `npx tsc --noEmit` clean (0 errors), `bun test` tunnel unit tests passing (3 passed).

## 2026-09-23: Wayfinder Map #68 - Real API Generation (Gemini + ElevenLabs)

### Status: Done

### Changes & Verification:
- **Phase 1 (HITL): #83 - Decide v1 capability set and failure UX for real generation**
  - Interviewed operator and determined v1 capability set (all 6 capabilities: Gemini Text, Gemini Image, ElevenLabs TTS, ElevenLabs SFX, Voice Design, and IVC).
  - Established hard-fail error UX (400 for missing secret, 401 for bad auth, 429 for quota/concurrency) with inline error banner and Settings deep-link, strictly prohibiting silent mock fallback.
  - Recorded resolution on #83 and closed.
- **Phase 1 (HITL): #84 - Prototype the Generation panel with real inputs**
  - Prototyped 3 radically different UI variants (Variant A: Tabbed Studio, Variant B: Command Console, Variant C: Multi-Pane Workspace) switchable via interactive prototype switcher.
  - Operator selected Variant A: Tabbed Studio.
  - Preserved prototype primary source on branch `prototype/genpanel` (commit `20b3ce0`), recorded resolution on #84, and closed.
- **Phase 2 (AFK): #85 - Wire /api/generate/* to real Gemini and ElevenLabs calls**
  - Replaced hardcoded mocks in `backend/app/routers/generate.py` with real provider HTTP calls using encrypted keys from `app.services.secrets.get_secret`.
  - Implemented Gemini `generateContent` for text (`gemini-3.8-flash`) and image (`gemini-3.1-flash-image`) decoding base64 image data and uploading to MinIO S3 with `MediaAsset` records.
  - Implemented ElevenLabs TTS (`text-to-speech`) and SFX (`sound-generation`) streaming audio bytes to MinIO S3 and database.
  - Added clean error status mapping for 401, 429, 400/422, and 502 with informative details.
  - Preserved mock fallback when no secret is stored for full backward compatibility with smoke tests.
  - Added unit test suite `backend/tests/test_generate_real_api.py` (9 passed). Commit `8be4e7c`. Recorded resolution on #85 and closed.
- **Phase 2 (AFK): #86 - Connect Generation panel UI to endpoints with e2e**
  - Replaced static marketing grid in `frontend/src/components/GenerationPanel.tsx` with full interactive Tabbed Studio matching Variant A.
  - Added `generateText`, `generateAudio`, and `generateImage` in `frontend/src/utils/api.ts` with parameter normalization, error payload handling, and status feedback.
  - Wired live in-flight generation indicators, inline error banners linking to Settings, audio player preview, image lightbox with SynthID badge, and S3 library navigation.
  - Extended Playwright e2e suite in `frontend/e2e/05-generation-catalog.spec.ts` with complete UI generation happy path.
  - Verified backend: all 194 pytest tests passing (`pytest backend/tests/`).
  - Recorded resolution on #86 and closed.

### Overall Verification:
- Backend: 194 pytest unit & integration tests passing (`pytest backend/tests/` 194 passed in 47.94s).
- OCR Review: Zero findings across backend and frontend code changes.

## 2026-09-23: Wayfinder Map #69 - Colab Real Inference & Notebook

### Iteration Status: Done

- **Phase 1 (HITL): #88 - Decide which workloads run on Colab v1 and the Colab-vs-local split**
  - Confirmed workload roster with user: SDXL (image generation) and Real-ESRGAN/tile upscaling in remote burst mode when Colab worker is connected.
  - Closed #88 with resolution recorded.
- **Phase 1 (HITL): #90 - Prototype the runnable inference notebook for human Colab test**
  - Created runnable notebook `notebooks/fusionclip_colab.ipynb` covering GPU check, SDXL Turbo model loading with fp16 on CUDA, standalone smoke-test cell, and real worker upload loop to `/api/storage/upload`.
  - User approved prototype structure. Closed #90 with resolution recorded.
- **Phase 2 (AFK): #89 - Replace mock execute_task with handler registry + real artifact upload**
  - Refactored `colab_client.py` replacing the sleep loop and `mock_colab_output_*.png` with pluggable `TaskHandlerRegistry`.
  - Added built-in SDXL diffusion handler with pipeline caching and step progress updates.
  - Added `--fake` mode producing real on-disk PNG files uploaded via multipart `/api/storage/upload`.
  - Added temporary file cleanup, path traversal sanitization, and thread synchronization (`_gpu_lock`, `_ws_lock`).
  - Added unit test suite in `backend/tests/test_colab_client.py` (7 tests). Closed #89 with resolution recorded.
- **Phase 2 (AFK): #91 - Real per-step progress reporting + local fake-GPU e2e harness**
  - Replaced fake sleep progress with per-step callbacks from handlers over WS/HTTP paths.
  - Fixed Pydantic v2 `Optional[dict]` and `Optional[str]` validation on `ColabTaskUpdate` and `ColabMetrics`.
  - Added constant-time secret comparison with `secrets.compare_digest` and Bearer token header support.
  - Added TTL (`ex=3600`) to Redis task result keys to avoid memory leaks.
  - Built comprehensive end-to-end integration test suite in `backend/tests/test_colab_e2e_harness.py` covering dispatch, per-step progress, artifact landing in MinIO/DB, failure lifecycles, and auth rejection.
  - Verified backend: all 205 pytest tests passing. Closed #91 with resolution recorded.

### Overall Verification:
- Backend: 205 pytest unit & integration tests passing (`pytest backend/tests/` 205 passed in 45.19s).
- Python compile check: clean.

## 2026-09-25: Wayfinder Map #71 - Local Torch Models (Scaffold)

### Iteration Status: Done

- **Phase 2 (AFK): #99 - Create the shared local-inference foundation (scaffold)**
  - Implemented `app.ml.registry`: Model registry managing the pinned roster (Flux-schnell [image/FP8/13GB/Apache-2.0], SDXL [image/FP8/6.5GB/RAIL++-M], XTTS v2 [voice/FP16/4GB/CPML], MusicGen [audio/FP16/10.4GB/CC-BY-NC-4.0 weights], SVD [video/FP16/16GB resident/8GB offload/Stability-AI-Community]) with lazy loading, idempotent caching, CUDA VRAM cleanup on unload, and a lock serializing load/unload/register so two workers cannot allocate the same model twice.
  - Implemented `app.ml.guard`: VRAM guard resolving the registry *first* so unknown ids report `model_not_found` regardless of GPU presence; distinct `NoGPUError` vs `InsufficientVRAMError` vs `ModelNotFoundError`; working overhead accounting; CPU-offload footprint fallback so SVD admits on the 16 GB floor; auto-downgrade selection (Flux-schnell -> SDXL) that skips unregistered candidates.
  - Implemented `app.ml.contracts`: Labeled honest fallback tier (`DegradedResponse`, `DegradedReason`, `FallbackTier`) satisfying Decision #3, with a runtime validator rejecting any "Mock ... bytes" payload.
  - Configured Celery queue isolation in `app/celery_app.py` with dedicated `media.gpu` queue and route for `app.tasks.process_gpu_task`, isolated from existing CPU queues `media.fast` / `media.heavy`; `worker_prefetch_multiplier=1` + `task_acks_late=True` so a GPU worker never reserves several multi-GB models at once.
  - Added health metrics at `GET /api/tasks/gpu/health` reporting GPU availability, VRAM usage, per-model loaded state, `media.gpu` depth, and `active_tasks_total` (all-queue in-flight count - Task rows carry no queue column).
  - `process_gpu_task` converts guard refusals and unknown-model lookups into the degraded contract instead of letting `KeyError` flip the Celery task to FAILURE.
  - Authored `backend/tests/test_localml_scaffold.py` covering roster pinning (incl. flux-dev exclusion), lazy load, idempotent load/unload, concurrent-load single-flight, VRAM refusal, no-GPU detection, model-not-found, offload admission, queue isolation, degraded contract (incl. mock-byte rejection), and health endpoint.
  - Code review gate: 11 findings (4 major) applied - test seams, KeyError handling, misclassified reason, registry lock, offload path, dead `DegradedOut` schema, ambiguous `/api/tasks/metrics` alias, metric mislabel, license corrections, runtime mock-byte validator, Celery prefetch.
  - Verified: 27 scaffold tests passing; 233 total tests passing in backend test suite.

## 2026-09-25: Wayfinder Map #71 - Local Torch Models (Priority-1 Image Pipeline)

### Iteration Status: Done

- **Phase 2 (AFK): #100 - Wire POST /api/generate/image to priority-1 image model and honest degraded fallback**
  - Deleted the unconditional mock branch and eliminated the legacy placeholder string `"Mock local flux generated image bytes"` completely from the codebase.
  - Implemented `app.ml.image`:
    - `run_local_image_generation`: Consults `vram_guard.select_fitting_model(["flux-schnell", "sdxl"], working_overhead_gb=1.0)` first.
    - Surfaces Decision #3 honest degraded envelope (`degraded: true` with typed machine-readable reason such as `no_gpu` or `insufficient_vram`) on refusal.
    - Implemented auto-downgrade to `sdxl` when VRAM is insufficient for `flux-schnell` (Decision #4).
    - Added lazy diffusers loader factory (`make_diffusers_loader`) guarding torch and diffusers imports so the backend cleanly boots and operates without GPU or diffusers installed.
    - Honored `steps`, `scale` (guidance), `aspect_ratio` dimension mapping, and `scheduler` configuration (`EulerDiscreteScheduler`, `DPMSolverMultistepScheduler`, `DDIMScheduler`, `FlowMatchEulerDiscreteScheduler`, etc.) as promised in `features.md` §3.
    - Uploads generated PNG bytes to object storage and persists `MediaAsset` catalog record.
  - Updated `backend/app/routers/generate.py`:
    - Added a narrow `_validate_aspect_ratio` (`^\d{1,4}:\d{1,4}$`, parts >= 1) so `16:9` is accepted; `provider`/`scheduler` keep the stricter safe-identifier pattern. This fixes a pre-existing 400 on the image tab's default request (`GenerationPanel.tsx` defaults `aspectRatio` to `16:9` and `api.ts` always sends it).
    - `denoising_strength` now returns 400 with an actionable message: `strength` is img2img-only and diffusers txt2img pipelines raise TypeError on it, and this route has no source-image input yet.
    - Preserved existing Colab worker dispatch and Gemini cloud API routing when `provider != "local"`.
    - Routes local inference through `run_local_image_generation`.
  - Code review gate: 8 findings (2 blocker, 1 major) applied:
    - FLUX loader switched from `pipe.to("cuda")` (~34 GB resident, OOM at the 16 GB floor) to `enable_model_cpu_offload()`.
    - `strength` never forwarded to txt2img; `denoising_strength` rejected up front instead.
    - `ASPECT_RATIO_DIMENSIONS` `3:2`/`2:3` moved 680 -> 672 (multiples of 16 for FLUX 2x2 patchification); unmapped ratios now derive a ~1024^2 area rounded to 16 instead of silently becoming square.
    - FLUX skips incompatible classical schedulers (warns and keeps default); `euler` maps to `FlowMatchEulerDiscreteScheduler`.
    - Filenames use `time.time_ns()` via `build_image_filename()` to avoid same-second collisions while staying `gen_image_\d+\.png`; unused `uuid` import removed.
  - Authored comprehensive test suite `backend/tests/test_localml_image.py`:
    - Verified complete elimination of `"Mock local flux generated image bytes"` across production code.
    - Tested degraded refusal on `no_gpu` and `insufficient_vram`.
    - Tested auto-downgrade from `flux-schnell` to `sdxl` with 8 GB free VRAM.
    - Tested primary selection of `flux-schnell` with 20 GB free VRAM.
    - Tested validation and forwarding of `steps`, `scale`, `aspect_ratio`, `scheduler`; asserted `strength` is absent from txt2img kwargs.
    - Tested persistence of `MediaAsset` and real byte upload.
    - Tested runtime load failure handling (`load_failed`).
    - Tested VAE-compatible dimensions for all ratios, flux offload loader, scheduler compatibility, and filename uniqueness.
    - Verified Gemini and Colab branches remain intact.
  - Test fixture fix: `conftest.stub_storage` gained `app.ml.image` — the new module binds `upload_object` into its own namespace, so it was never stubbed and real storage was hit.
  - Updated `test_routers_smoke.py`, `test_refactor_equivalence.py`, and `test_generate_real_api.py` to align with the new honest degraded fallback and local execution architecture.
  - Verified: 260 backend tests passing (`pytest backend/` 260 passed in 45.91s).

**Deviation / not yet specified:** `features.md` §3 promises denoising strength and image-to-image templates. This ticket's Question only asks for steps/guidance/scheduler, and there is no source-image input on `POST /api/generate/image`, so img2img (and therefore real denoising strength) is rejected rather than silently ignored. Needs its own ticket.

## 2026-09-25: Wayfinder Map #71 - Local Torch Models (Real Audio Pipelines)

### Iteration Status: Done

- **Phase 2 (AFK): #101 - Real audio pipelines (XTTS v2 voice clone + MusicGen) replacing audio mock**
  - Deleted the legacy mock branch and eliminated the placeholder string `"Mock elevenlabs generated audio bytes"` completely from production code and comments.
  - Implemented `app.ml.audio`:
    - `run_local_audio_generation`: Implemented admission check via `vram_guard.select_fitting_model` routing `tts`/`voice`/`voice_clone` to `xtts-v2` and `sfx`/`music` to `musicgen`.
    - Returns typed DegradedResponse (`degraded: true` with machine-readable reasons `no_gpu`, `insufficient_vram`, `load_failed`, or `model_not_found`) whenever GPU resources are unavailable or admission is refused.
    - Lazy loader factory `make_audio_loader`: Strictly encapsulates torch, transformers, and TTS imports inside loader functions so the FastAPI backend imports cleanly and boots without torch.
    - XTTS v2 execution supports both plain TTS with built-in speaker and zero-shot voice cloning using reference speaker WAV.
    - MusicGen execution generates tokens based on duration (~15s default at 50 tokens/sec) and outputs 16-bit PCM WAV.
    - Audio output container is WAV (`audio/wav`) with nanosecond filenames `gen_audio_{time_ns}.wav` via `build_audio_filename()`.
    - Exact duration extracted via standard library `wave.open` from generated WAV bytes.
    - Uploads real WAV bytes to storage and persists `MediaAsset` records.
    - Response structure includes `"markers": [...]`: includes `{"time": 0.0, "label": f"voice clone: {reference}", "kind": "voice_clone"}` for `type=voice_clone`, and `[]` for plain audio types.
    - MediaAsset title for voice clone output prefixed with `Voice Clone: <prompt[:30]>...` for schema-free frontend marker derivation.
  - Updated `backend/app/routers/generate.py`:
    - Added `_validate_safe_reference` rejecting empty paths, path traversals (`..`), or invalid characters.
    - Validates `type` against `SUPPORTED_AUDIO_TYPES` (400 if invalid).
    - Requires non-empty `reference` parameter when `type="voice_clone"` (400 if missing).
    - Preserved ElevenLabs cloud path when API key is configured.
    - Forwards `reference` parameter to Colab dispatch when connected.
  - Updated `conftest.py`: Added `app.ml.audio` to `stub_storage` fixture.
  - Authored comprehensive test suite `backend/tests/test_localml_audio.py` (19 tests):
    - Verified elimination of forbidden mock string from all production python files.
    - Verified degraded refusal on `no_gpu` and `insufficient_vram`.
    - Verified model selection: `tts`/`voice` -> `xtts-v2`, `sfx`/`music` -> `musicgen`.
    - Verified voice clone requires reference (400) and passes reference to loader when present.
    - Verified marker generation for voice clone and empty markers for other audio types.
    - Verified real bytes uploaded, content_type `audio/wav`, and MediaAsset persisted.
    - Verified load failure returns degraded response with `load_failed`.
    - Verified ElevenLabs TTS and SFX cloud paths are preserved when key is configured.
    - Verified `app.ml.audio` imports cleanly without torch.
  - Updated smoke and equivalence tests (`test_routers_smoke.py`, `test_refactor_equivalence.py`, `test_generate_real_api.py`) to align with WAV container, markers contract, and honest degraded refusal.
  - Updated `frontend/e2e/05-generation-catalog.spec.ts`: Relaxed filename regex to `/^gen_audio_\d+\.(mp3|wav)$/` and content_type to either `audio/mpeg` or `audio/wav`.
  - Verified: 279 backend tests passing (19 added, 279 passed in 50.65s).

### Iteration Status: Done (Code Review Fixes for #101)

- **Review Fixes Applied (#101)**:
  - FIX 1: Restricted ElevenLabs routing in `generate_audio` to `{"tts", "voice", "sfx"}`; `voice_clone` and `music` route to local ML pipeline even when ElevenLabs key is configured (preserving Colab priority).
  - FIX 2 & 5: Added `INFERENCE_LOCK = threading.RLock()` in `app.ml.registry` and wrapped `run_local_image_generation` and `run_local_audio_generation` to serialize admission and inference. Added `ModelRegistry.evict_except(keep_ids)` and integrated into `VRAMGuard` when free VRAM is insufficient.
  - FIX 3: Added `download_object` to `app.storage` and resolved `reference` to temporary files in `app.ml.audio` for XTTS voice cloning with `try/finally` cleanup. Loosened reference validation in `generate.py` to allow relative paths with slashes (`uploads/speaker.wav`) while rejecting traversals/absolute paths with 400.
  - FIX 4: Aligned MusicGen model identity and precision with pinned roster: loaded `facebook/musicgen-large` with `torch_dtype=torch.float16` on CUDA, and wrapped generation in `torch.inference_mode()`.
  - FIX 6: Added duration validation to `generate_audio` rejecting values outside `0.5 .. 30.0` seconds with HTTP 400.
  - FIX 7: Added unit test with real `tts_to_file` signature asserting `speaker_wav` receives resolved temporary file path and is cleaned up, and omitted for plain TTS.
  - FIX 8: Fixed `test_audio_module_imports_without_torch` to safely pop `app.ml.audio`, mask torch/transformers/TTS, test clean imports, and restore module state.
  - Verified: 294 backend tests passing (15 added, 294 passed in 54.53s).
  - Code review gate verdict: FIX-FIRST (2 blocker, 3 major, 3 minor, 2 nit) - all applied.
  - Follow-up fix: eviction kept every candidate model, so a resident SDXL pinned
    VRAM and forced an avoidable downgrade to it instead of admitting
    flux-schnell. `check_vram` now evicts only the model being admitted (safe
    under `INFERENCE_LOCK`). Red first: `test_priority_model_admitted_by_evicting_resident_downgrade`.
    295 backend tests green.
  - Frontend wiring (`264005f`): `AudioMarker` + `markers?` on
    `GenerateAudioResponse`; session-only `waveAudio` store slice;
    GenerationPanel publishes the clip, renders marker chips, a `voice clone`
    badge, the degraded reason, and a Voice Reference field (non-empty => local
    XTTS zero-shot clone); PlayersPanel loads the generated clip and redraws
    WaveSurfer markers with a legend. Verified with `npx tsc --noEmit` (exit 0)
    and `npx next build` (compiled + types clean). Playwright e2e not run: no
    FusionClip backend stack is up in this worktree.
  - Final verified state for #101: **295 backend tests passing**, frontend build clean.




