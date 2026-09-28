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

## 2026-09-24: Wayfinder Map #70 - Magnific Core Upscaler (#96 ship)

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

## 2026-09-25: Wayfinder Map #71 - Local Torch Models (SVD Video Pipeline)

### Iteration Status: Done

- **Phase 2 (AFK): #102 - Implement SVD image-to-video pipeline and task wiring**
  - Implemented `app.ml.video`:
    - `run_local_image_to_video`: Implemented admission check via `vram_guard.check_vram("svd")` under `INFERENCE_LOCK`.
    - Returns typed DegradedResponse (`degraded: true` with machine-readable reasons `no_gpu`, `insufficient_vram`, `load_failed`) on GPU refusal or runtime errors.
    - Decodes conditioning image bytes and validates image integrity via PIL (raises `ValueError` for unreadable/corrupt images).
    - Lazy loader factory `make_video_loader`: strictly encapsulates diffusers and torch imports so the backend boots without torch installed, with CPU offload on CUDA (`enable_model_cpu_offload()`).
    - Reports denoising progress (0..79%) via `callback_on_step_end`.
    - Encodes PIL frames to H.264 MP4 using system `ffmpeg` binary with frame progress scraping from stderr (80..99%).
    - Generates nanosecond-timestamped pure-digit filenames (`gen_video_{time_ns}.mp4`).
    - Uploads MP4 to storage and creates `MediaAsset` catalog record in DB.
  - Extended `process_gpu_task` in `app/tasks.py`:
    - Added op dispatch for `op == "image_to_video"`.
    - Resolves source bytes from storage via `download_object`.
    - Progress callback updates Celery state (`meta={"percent": int, "status": str}`), publishes to Redis channel `task_updates`, and upserts `Task` row in DB.
    - Preserved existing scaffold behavior for other models.
  - Added endpoint `POST /api/generate/video` in `app/routers/generate.py`:
    - Validates `source` relative path (rejects traversals `..`, absolute paths, backslashes, empty) and resolves via `download_object` (returns 400 if missing or unreadable).
    - Validates bounds: `num_frames` in 2..25 (400 if outside), `fps` in 1..30 (400 if outside).
    - Preserves Colab priority when worker is connected.
    - Dispatches to `process_gpu_task.delay("svd", ...)` and returns `{"task_id": ..., "status": "PENDING", "type": "video", ...}`.
  - Updated `backend/tests/conftest.py` adding `app.ml.video` to `stub_storage`.
  - Authored comprehensive test suite `backend/tests/test_localml_video.py` (18 tests passing).
  - Verified: 313 backend tests passing (18 added, 313 passed in 52.76s).

- **Phase 2 (AFK): #102 Backend Review Gate Fixes**
  - **F1 BLOCKER**: Updated `make_video_loader` in `app/ml/video.py` to pick dtype dynamically based on device (`torch.float16 if cuda else torch.float32`).
  - **F3 MAJOR**: Wrapped `process_gpu_task` in `app/tasks.py` with `try/except Exception` to record `FAILED` status and error in DB `Task` table and publish terminal failure to Redis channel `task_updates`. Published terminal `task_updates` event for degraded results with status `FAILED` to ensure frontend pollers and `FileManager` observe completion.
  - **F4 MAJOR**: Enforced child process cleanup in `encode_frames_to_mp4` via `try/finally` (killing child and closing stderr on exit/error) and added bounded timeout (default 60s) raising `VideoEncodingError`.
  - **F7 MINOR**: Removed local host disk fallback reads in `app/routers/generate.py` and `app/tasks.py` to maintain strict object-storage isolation.
  - **F9 NIT**: Enhanced `VideoEncodingError` with `returncode` and `stderr` fields and added focused test exercising genuine ffmpeg failure with non-zero exit code.
  - Note: `INFERENCE_LOCK` and `ModelRegistry._lock` are single-process `threading.RLock` primitives; cross-process coordination across API and Celery workers is tracked as an open item on map #71.
  - Verified: 320 passed in pytest suite (7 new tests added, 320 passed in 57.19s); lazy import check verified with no torch installed.

- **Phase 2 (AFK): #102 Frontend Implementation + Review Gate Fixes**
  - `api.ts`: `startVideoGeneration(source, num_frames, fps)` + `VideoGenerationResult`; session-only `genVideo` store slice (`url`, `filename`, `fps`).
  - GenerationPanel: new `SVD Image-to-Video` modality (library `file_path`, frames 2-25, fps 1-30) dispatching to `/api/generate/video` and polling the existing `/api/tasks/status/{id}` contract every 1.5s, rendering the same `info.percent` / `info.status` bar the file-manager job panel uses (denoise 0-79%, encode 80-99%). Generate button validates `source` instead of free text for this modality.
  - Review fixes: `setVideoResult(info)` before the degraded early-return (the refusal card was unreachable dead code) + `Status: DEGRADED (200 OK)` + amber border; 10-minute polling deadline so a dead worker surfaces a timeout instead of polling forever; `formatTaskFailure()` for structured Celery failures; `GeneratedVideo.fps` synced into PlayersPanel so frame stepping matches the clip; nested ternary split.
  - PlayersPanel: loads the generated clip into the video player and captions it.
  - Deviations: Playwright e2e not run — no FusionClip stack in this worktree (running ports belong to another project); UI verified with `tsc` + `next build` only.
  - Verified: `npx tsc --noEmit` exit 0, `npx next build` exit 0, backend 320 passed.





### Iteration Status: Done

- **#96 Ship presets, categories, bulk, compare, FileManager rewiring**
  - Backend: `upscale.py` unique `task_token` output paths + status lookup via `file_path.contains(token)` (fixes 6-char task_id prefix collisions). 4 new tests in `test_upscale_ship.py`.
  - Frontend: `utils/upscale.ts` helpers, `types.ts` piecewise slider-mapping parity, `api.ts` upscale client, `FileManager.tsx` live Upscale button/modal/jobs panel/polling, `VariantA.tsx` real source picker + bulk queue (max 8) + compare-on-complete.
  - E2E: new `09-upscaler.spec.ts` (3 tests). Replaced corrupt shared `PNG_HEADER` fixture with PIL-verified 69-byte PNG (hand-rolled bytes had broken IDAT stream — upload accepted but pipeline decode failed).
  - Local no-Docker stack for e2e: moto S3 :9000, backend :8001, frontend :3001 (8000/3000 occupied by another worktree).

### Overall Verification:
- Backend: `pytest backend/tests/ -q` → **223 passed**.
- Typecheck: `tsc --noEmit` → TSC_OK.
- Unit: `bun test frontend/src/utils/` → 10 pass.
- E2E: `09-upscaler.spec.ts` → **3 passed** (registries, FileManager flow, Magnific panel).
- Issue #96 closed with resolution comment.

## 2026-09-25: Merge origin/main into the #96 branch (post-#96 integration)

### Iteration Status: Done

- **Merged `origin/main` (merge-base `843569d`) — 13 conflicts resolved, keeping #96 while preserving main's new features.**
  - `models.py`: `Vector(384)` (our embedding scheme) + main's `source_path` column; alembic `b7e0c1a2d3f4` merge revision for 3 heads.
  - `generate.py`: main's file as base + 15 count-asserted grafts (lazy torch/diffusers imports, pipeline cache globals main was missing, `_save_asset` embedding, HTTPException guards, ElevenLabs sfx/tts branches, Gemini image branch, image local→mock fallback).
  - `services/gemini.py` / `services/elevenlabs.py`: REST helpers (`call_gemini_generate_content`, `synthesize`, `generate_sound_effect`) + error mappers.
  - `api.ts`: union of both sides; dropped main's dead legacy `startUpscale(path,…)` (zero callers).
  - `FileManager.tsx`: union imports/state; main's drag-drop + batch-upload UI wrapped around our Magnific jobs panel; our modal flow kept (pinned by e2e); main's `UpscalerPanel` stays reachable via its Sidebar tab; removed main's now-unused `useStore` destructure.
  - `useStore`/`Sidebar`/`page.tsx`: both upscale tabs wired; `tasks.py`: `upscale`/`video_upscale` in `ALLOWED_TASK_TYPES`.
  - Deps installed into the project venv: `elevenlabs==2.69.0`, `google-genai`, `scipy` (scipy also declared in `requirements.txt`); torch/diffusers deliberately NOT installed (generate.py torch paths made lazy).
- **Verification (all gates):**
  - Backend: `pytest backend/tests/ -q` → **304 passed** (pre-merge: 301 +3; fixed test asserts: CLIP 1536→384, `eleven_tts_` filename, unknown-task-type since upscale is now real).
  - Typecheck: `tsc --noEmit` → 0 errors.
  - Unit: `bun test frontend/src/utils/` → 10 pass.
  - E2E: `09-upscaler.spec.ts` → **3 passed** (first cold-run attempt failed a 20s upload-visibility timeout during Next/moto warm-up; warm re-run green, isolated re-run green).
- **Flags for review:** main's CLIP hybrid search not ported (fastembed/384 kept); both upscale tabs in Sidebar (product cleanup); `aspect_ratio`/`provider` query params dropped from `generateImage` (frontend still sends them, FastAPI ignores); image-gemini/audio-key responses carry no `colab` key (matches both sides' existing key-sets); main's `09-upscaler-before-after.spec.ts` needs Redis+Celery worker — no redis binary/sudo in this env (docker stack covers it; API-level upscale paths covered by pytest).

## 2026-09-25: CodeRabbit review response on PR #129

### Iteration Status: Review

- CodeRabbit posted **9 actionable findings**. All replied to on the PR:
  - **6 fixed** (`0c30761`): backfill `max_rows` cap (CWE-400; admin-auth half parked — no auth framework exists), upscale status exact-suffix + `upscale_` id guard, embedding failed-load sentinel + lock, upscaler `db.rollback()` before failure/progress commits, conftest patch target `app.services.upscaler.SessionLocal`, semantic tests skip when model unavailable. New tests: backfill cap (+400 invalid), status near-miss guard.
  - **3 parked verbatim for maintainers**: hash-fallback embedding persistence (data integrity, heavy), upscale job memory bounds >1.3 GB/job (architecture, heavy), Colab tunnel intent-vs-status separation (frontend redesign, heavy).
- **GitGuardian check red (parked for human)**: scans all 22 PR commits; flags commit `6eb6f9d` for test placeholder `xi-stored-key-0001` in `"api_key":` context (incident 35968525, occurrences 299506848-50). Placeholders were renamed to `unit-test-placeholder-value*` at head (`0c30761`), but per-commit scanning keeps the historical finding — clearing requires marking the incident a false positive in the GitGuardian dashboard (needs repo owner access). `main` is branch-unprotected, so the red check does not block merge.
- **Verification:** `pytest backend/tests/ -q` → **306 passed** (304 + 2 new); tsc/bun/e2e unaffected (backend-only changes; e2e green earlier this session at head `69411cd` frontend state).

## 2026-09-26: Wayfinder Map #72 - Batch Select + Zip Export (#106)

### Iteration Status: Done

- **#106 Implement batch select + zip export with derivatives**
  - **Backend (`POST /api/export/batch`, `GET /api/export/{task_id}`, `GET /api/export/download/{task_id}`)**:
    - Added `app/routers/export.py` registered in `app/main.py`.
    - Validates selection: rejects empty array/missing payload with 400 Bad Request; rejects unknown asset IDs with 400 Bad Request.
    - Records job in existing `Task` model (`name="batch_export"`, `status="PENDING"`) enabling unified queue visibility (#107).
    - Status endpoint returns presigned download URL when `COMPLETED`, progress updates during processing, and 404 for nonexistent tasks.
    - Added Celery task `app.tasks.export_assets_zip` collecting original assets and all linked derivatives (`MediaAsset.source_path`), safely bundling them into `exports/export_{task_id}.zip` in MinIO/S3 with collision-resistant arcnames.
    - Resilient failure handling: gracefully skips missing/unreadable derivatives, handles 0-byte entries safely, and fails task on storage upload error.
  - **Frontend (`CatalogPanel.tsx`, `utils/api.ts`, `utils/export.ts`)**:
    - Chose `CatalogPanel.tsx` as the primary UI surface where database-backed indexed assets and their generated derivatives reside (as opposed to `FileManager.tsx` which handles raw unindexed S3 buckets).
    - Added multi-select checkboxes for both Grid and List layouts with Select All / Deselect All controls.
    - Added selection toolbar showing dynamic file count including derivatives, toggle for derivative inclusion, and Export ZIP action.
    - Implemented background status polling with real-time progress bar, ready badge, and automated browser download trigger.
    - Added utility module `utils/export.ts` with comprehensive unit tests in `utils/export.test.ts`.
- **Verification:**
  - Backend: `HF_HUB_OFFLINE=1 pytest` → **327 passed, 2 skipped** (all 15 new batch export tests passed).
  - Frontend: `bun test src/utils/` → **23 passed, 0 failed** (all 4 new export unit tests passed).
  - Typecheck: `npx tsc --noEmit` → **0 errors**.
  - Production build: `npm run build` → **Compiled successfully**.

## 2026-09-26: Code review response on #106

### Iteration Status: Done

- **Addressed 7 review findings**:
  1. **Memory DoS prevention**: capped `AssetBatchExportIn.asset_ids` at `max_length=100`, mapped validation errors on `/api/export` to 400 Bad Request, replaced RAM `BytesIO` zip buffering with `tempfile.NamedTemporaryFile` disk streaming and cleanup in `finally:`. Added test for >100 rejection.
  2. **Zip-slip traversal protection**: added `sanitize_archive_entry_name` normalizing backslashes, using `os.path.basename`, and rejecting `.`/`..`/empty names. Added test asserting malicious traversal paths (`uploads/../../evil.sh`) and Windows-style paths strip separators.
  3. **Duplicate entry exclusion**: filtered `~MediaAsset.id.in_(selected_ids)` when querying derivatives so selecting both parent and child doesn't duplicate the child. Added test verifying count = 2.
  4. **Frontend polling failure resilience**: added consecutive error counter (max 5) to status polling interval, safely stopping spinner and clearing task ID on connection loss.
  5. **UI badge overlap fix**: moved media type badge in Grid card from `top-2.5 left-2.5` to `top-2.5 right-2.5`, avoiding collision with selection checkbox.
  6. **Failure traceback capture**: set `db_task.traceback = traceback.format_exc()` in `export_assets_zip` error handler; asserted in tests.
  7. **Nits resolved**: cleared `selectedAssetIds` on export completion; computed `exportSummary` against `mediaList` so counts persist through filter changes.
- **Verification:**
  - Backend: `HF_HUB_OFFLINE=1 pytest` → **330 passed, 2 skipped** (18/18 batch export tests passed).
  - Frontend: `bun test src/utils/` → **23 passed, 0 failed**.
  - Typecheck: `npx tsc --noEmit` → **0 errors**.
  - Production build: `npm run build` → **Compiled successfully**.

## 2026-09-26: Wayfinder Map #72 - Task Logs & Error Viewer (#108)

### Iteration Status: Done

- **#108 Capture stack traces into Task.logs and build error-log viewer**
  - Backend: Created `backend/app/task_logging.py` wiring Celery lifecycle signals (`task_prerun`, `task_postrun`, `task_failure`, `task_retry`) and fallback helper `_handle_task_failure`. Events (`started`, `failed`, `retry`, `finished`) stored as NDJSON in `Task.logs`. Full Python traceback saved to `Task.traceback` column, while `Task.logs` traceback is bounded (8KB cap + explicit truncation marker). Concurrency protected via thread-safety and bounded caps (max 50 events, 64KB). Added `logs` to `TaskListItem` response model in `backend/app/routers/tasks.py`.
  - Frontend: `frontend/src/utils/queue.ts` parser and formatting helpers (`parseTaskLogs`, `formatEventLabel`, `getEventBadgeStyle`, `hasTraceback`). `frontend/src/components/QueueDashboard.tsx` expanded row logs viewer (`TaskLogsViewer`) showing event badges, timestamp, failure diagnostics, collapsible monospace Python stack trace, and copy-to-clipboard button.
  - Tests: `backend/tests/test_task_logs.py` (6 tests covering success events, failure stack trace, oversized truncation, concurrent appends, API list exposure, edge cases). `frontend/src/utils/queue.test.ts` (8 new tests covering NDJSON parsing, JSON array fallback, legacy string wrapping, badge styles, traceback detection).

### Overall Verification:
- Backend: `pytest` → **318 passed, 2 skipped**.
- Frontend unit: `bun test src/utils/` → **32 passed**.
- Typecheck: `npx tsc --noEmit` → **clean (0 errors)**.
- Build: `npm run build` → **compiled successfully**.

## 2026-09-26: Code Review on #108 - Task Logs & Error Viewer

### Iteration Status: Done

- **Addressed all 7 review findings for #108:**
  - Blocker 1: Fixed upscale ID mismatch in `backend/app/routers/upscale.py` and `backend/app/routers/tasks.py` by switching to `apply_async(..., task_id=task_id)`. Audited all 7 `.delay()` dispatch sites across `backend/app/routers/*.py`.
  - Blocker 2: Removed duplicate manual retry logging in `_handle_task_failure`; relied on `task_retry` signal with deduplication by `retry_count`.
  - Blocker 3: Wrapped all 4 Celery signal handlers (`on_task_prerun`, `on_task_postrun`, `on_task_failure`, `on_task_retry`) in top-level `try/except Exception` logging blocks so signal failures never kill tasks.
  - Should-fix 4: Added `.with_for_update()` to task query in `append_task_event` for multi-process row locking.
  - Should-fix 5: Hardened bounds: bounded `error` with `truncate_text`; byte-trim loop prunes down to hard floor (2 events: initial + latest) and trims latest event's traceback/error to ensure row <= `MAX_LOGS_BYTES`.
  - Should-fix 6: List payload optimization: removed `logs` and `traceback` from `GET /api/tasks/list` (returning `event_count` instead); added `GET /api/tasks/{task_id}/logs`; implemented lazy loading with cache and error states in `QueueDashboard.tsx`.
  - Should-fix 7: Added tests in `backend/tests/test_task_logs.py` covering single retry event, signal handler failure swallow, `/logs` endpoint retrieval, and 2-event row with huge failed event within `MAX_LOGS_BYTES`.
  - Nit: Capped legacy raw-traceback fallback render in the UI at 10,000 characters while preserving full traceback copy.

### Overall Verification:
- Backend: `pytest` → **322 passed, 2 skipped** (10 tests in `test_task_logs.py`).
- Frontend unit: `bun test src/utils/` → **32 passed**.
- Typecheck: `npx tsc --noEmit` → **clean (0 errors)**.
- Build: `npm run build` → **compiled successfully**.

## 2026-09-26: Subtitle tracks - extract/upload and player support (#109)

### Status: Done

### Changes & Verification:
- **Embedded-track extraction & Sidecar upload backend**:
  - Added `SubtitleTrack` model in `backend/app/models.py` with foreign key cascade to `media_assets.id` and Alembic migration `c3d4e5f6a7b8_add_subtitle_tracks_table.py`.
  - Added `backend/app/services/subtitles.py` providing probe with `ffprobe -select_streams s`, stream extraction to WebVTT with `ffmpeg -map 0:<stream> -c:s webvtt`, graceful skipping of bitmap codecs (e.g. PGS, DVD), error degradation when ffmpeg is missing, and `.srt` to `.vtt` conversion.
  - Added subtitle endpoints in `backend/app/routers/media.py`:
    - `GET /api/media/{asset_id}/subtitles` - list tracks
    - `POST /api/media/{asset_id}/subtitles` - upload sidecar (.vtt / .srt) with size and cue validation
    - `POST /api/media/{asset_id}/subtitles/extract` - on-demand embedded-track extraction
    - `DELETE /api/media/{asset_id}/subtitles/{track_id}` - delete track from DB and S3
    - `GET /api/media/{asset_id}/subtitles/{track_id}/content` - direct WebVTT stream
  - Wired extraction into video upload ingest in `backend/app/routers/storage.py`.
- **Frontend Player & Track Switching UX**:
  - Added `frontend/src/utils/subtitles.ts` with VTT validation, SRT conversion, cue parsing, track label normalization, and native DOM `TextTrack` mode synchronization.
  - Added API client helpers in `frontend/src/utils/api.ts` (`fetchAssetSubtitles`, `uploadAssetSubtitle`, `extractAssetSubtitles`, `deleteAssetSubtitle`).
  - Updated `PlayersPanel.tsx` with:
    - HTML5 `<track>` tags inside `<video crossOrigin="anonymous">`
    - Subtitle track selector dropdown with explicit "Off" option
    - Track error handler (`onError`) so 403 or network failure degrades gracefully
    - Extract Subtitles action button for library videos
    - Sidecar `.vtt` / `.srt` upload support
- **Verification**:
  - Backend: `pytest tests/test_subtitles.py` → **22 passed**.
  - Frontend: `bun test src/utils/` → **25 passed** across 3 test files (15 new subtitle tests).
  - Typecheck: `tsc --noEmit` → 0 errors.
  - Build: `npm run build` → compiled successfully.

## 2026-09-26: Code review fixes for #109 (subtitles)

### Status: Done

### Changes & Verification:
- **Blocker 1 (Playback breakage / CORS)**:
  - Removed `crossOrigin="anonymous"` from `<video>` element in `PlayersPanel.tsx` to prevent presigned MinIO URLs from failing with 404/CORS.
  - Updated subtitle serialization `_serialize_subtitle` in `backend/app/routers/media.py` to emit relative proxy URL `/api/media/{asset_id}/subtitles/{track_id}/content`.
  - Added `resolveSubtitleContentUrl()` in `frontend/src/utils/api.ts` to prepend `API_BASE_URL` when consuming subtitle track URLs, ensuring `<track src>` hits the CORS-ready FastAPI proxy endpoint.
- **Blocker 2 (Async upload extraction via Celery)**:
  - Added `@celery.task(name="app.tasks.extract_media_subtitles")` in `backend/app/tasks.py` and routed to `media.fast` queue in `backend/app/celery_app.py`.
  - Updated `backend/app/routers/storage.py` to dispatch `extract_media_subtitles.delay(asset.id)` without passing file bytes or blocking request responses.
- **Should-fix 3 (Subprocess timeouts)**:
  - Added `timeout=30` to `ffprobe` and `timeout=60` to `ffmpeg` in `backend/app/services/subtitles.py`, catching `subprocess.TimeoutExpired` gracefully with logging.
- **Should-fix 4 (Extraction idempotency)**:
  - Updated `extract_and_save_embedded_subtitles()` to query existing `(asset_id, file_path)` records before insert, preventing duplicate rows on re-runs.
- **Should-fix 5 (API catalog fetch)**:
  - Replaced bare `fetch('/api/media')` in `PlayersPanel.tsx` with typed `fetchMediaCatalog()`.
- **Should-fix 6 (Collision-safe sidecar keys)**:
  - Included `uuid4().hex[:8]` in sidecar storage paths (`subtitles/{asset_id}/sidecar_{stem}_{token}.vtt`).
- **Nits 7 & 8 (Memory leaks & DOM cleanup)**:
  - Added `URL.revokeObjectURL()` cleanup in `PlayersPanel.tsx` on unmount/replaces for audio, video, and local subtitle blob URLs.
  - Removed redundant custom DOM subtitle text overlay so native HTML5 text track rendering handles cue display.
- **Verification**:
  - Backend full suite: 329 passed, 2 skipped across all test files (100% green).
  - Frontend: `bun test src/utils/` (27 passed), `tsc --noEmit` (0 errors), `npm run build` (successful).

## 2026-09-26: Sync pass — rebase map #71 onto `main` (prerequisite for map #73)

### Iteration Status: Done

**Why:** map #73 (Skin Enhancer) needs *both* the localml VRAM-guarded registry (`app/ml/`) and the upscaler's `MediaAsset.source_path` lineage + `BeforeAfterModal`. Before this pass the worktree had only the former; `main` had only the latter.

**What changed:**
- `git rebase origin/main` on `t3code/f166906d` — replayed all 22 localml commits (was 45 behind / 22 ahead; now 0 behind / 22 ahead). 6 conflict rounds.
- `backend/app/routers/generate.py` rebuilt from `origin/main` + the three localml route rewrites. Deleted dead `load_flux_pipeline` / `load_sdxl_pipeline` / `load_xtts_pipeline` / `load_chattts_pipeline` / `_generate_local_tts_audio` (localml had removed them); kept `load_musicgen_pipeline` + `/api/generate/music` (main-only, still routed directly to transformers). Route list verified 11 in, 11 out.
- `backend/app/tasks.py`: consolidated the duplicated import block, dropped the duplicate `process_multimedia_task` (kept the `**upscale_kwargs` superset, which the upscaler route needs).
- `backend/app/routers/generate.py`: `/api/generate/tts` no longer returns `b"Mock elevenlabs generated audio bytes."`; missing key is now 503 via `_no_elevenlabs_key_http_503()`. `/api/generate/audio` ElevenLabs failures are wrapped as 502.
- Tests repointed at the service-module seams (`elevenlabs_service.synthesize` / `.generate_sound_effect`, `gemini_service.call_gemini_generate_content`) and updated where they pinned the pre-#101 audio contract (no-key behaviour, stability/clarity passthrough moved to `/api/generate/tts`, `colab` key removed from the image response shape).

**Verified:**
- `backend`: 495 passed, 2 skipped (`test_semantic_search` skips without the fastembed model), 0 failed. 210s.
- `frontend`: `npx tsc --noEmit` clean; 62 unit tests pass (`npx tsx --test src/utils/*.test.ts`).
- `next lint` unavailable — the repo has no ESLint config (pre-existing; `next lint` offers to scaffold one interactively).

**Not done / parked:** `main` and `master` are still separate lines. This branch is 22 commits ahead of `origin/main` and needs a PR to land. `TECH_DEBT.md` entry: duplicate `list_tasks` / `retry_task` in `app/routers/tasks.py` (pre-existing on `main`, causes FastAPI "Duplicate Operation ID" warnings).

## 2026-09-26: Skin-enhance backend endpoint + engine integration (#112, map #73)

### Iteration Status: Done

**Why:** the map's backend half. Faithful runs GFPGAN, Creative/Flexible run DiffBIR (both Apache-2.0), the five Magnific Flexible presets are a static prompt/guidance/noise table, and the output has to be a `skin_enhanced/<stem>_<token>.png` derivative with `MediaAsset.source_path` lineage so the existing `BeforeAfterModal` pairs it with no new UI.

**What changed:**
- `backend/app/ml/skin_enhancer.py` (new, ~880 lines). Ticket-citing module docstring; numbered-phase executor docstring; all torch / gfpgan / facexlib / diffusers imports confined to the loader closures so the app boots on a machine with none of them. Holds the pure parameter mapping (`map_skin_detail_to_guidance`, `map_skin_detail_to_texture_retention`, `map_sharpen_to_percent`, `map_smart_grain_to_sigma`), the pure `get_flexible_preset` table, the PIL post-filters, the two engine adapters, and `run_skin_enhancement` wrapped in `INFERENCE_LOCK` with the eviction-invariant comment. Every non-obvious number carries its reason.
- `backend/app/routers/skin_enhance.py` (new). `POST /api/skin-enhance` + `GET /api/skin-enhance/presets`. Range/integrality/mode/preset/path validation lives in the route so out-of-range sliders are **400 with an actionable message** rather than pydantic's 422; every 400 detail leads with a machine-readable reason slug.
- `backend/app/ml/registry.py`: added `gfpgan` (1.5 GB, Apache-2.0) and `diffbir` (8.0 GB, Apache-2.0) to `PINNED_ROSTER`; module docstring now records why CodeFormer/SUPIR/StableSR/GPEN are absent. The GFPGAN comment states plainly that the upstream repo publishes **no** numeric figure and that 1.5 GB is a conservative choice, not a citation.
- `backend/app/ml/__init__.py`: exported the skin-enhance surface.
- `backend/app/main.py`: registered the router.
- `backend/tests/conftest.py`: added `app.ml.skin_enhancer` to the `stub_storage` module loop (miss this and tests silently hit the real S3 client).
- `backend/tests/test_skin_enhancer.py` (new, 54 tests).
- `backend/tests/test_localml_scaffold.py`: `test_pinned_roster_loaded_by_default` still asserts an **exact** roster set, so the two new ids were added and the four excluded engines were added as explicit negatives. The exactness was kept, not relaxed.

**Verified:**
- TDD: 52 tests written first, all 52 red (`52 failed in 6.73s`), then implemented to green.
- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` → **549 passed, 2 skipped, 0 failed** in 217.13s. Baseline was 495 passed, 2 skipped, 0 failed (210s); +54 = exactly the new file. The 2 skips are `test_semantic_search` (needs the fastembed model).
- `cd frontend && npx tsc --noEmit` → clean, exit 0 (no frontend files touched).
- `cd frontend && npx tsx --test src/utils/*.test.ts` → 62 tests, 62 pass, 0 fail.
- No `torch` / `diffusers` / `gfpgan` / `facexlib` installed in `.venv` and the whole new suite is green, which is the CI condition the ticket asked for.

**Verified by construction (not runnable here):** the two engine adapters' calls into the real GFPGANer / DiffBIRPipeline. Their loaders are covered with fake `torch`/`gfpgan`/`facexlib`/`diffusers` modules injected into `sys.modules` (tiling + offload asserted, dtype-by-device asserted, unknown-engine refusal asserted), but the actual face restore on a real GPU is untested. `docs/research/skin-enhancers.md` is research only; the DiffBIR condition-noise unit differs between the upstream repo's webui (0..1) and the diffusers port (0..100) and the adapter converts explicitly.

**Not done / visible gaps:**
- Ticket #137 owns the panel; `GET /api/skin-enhance/presets` publishes the surface so it does not hardcode a second copy of the contract.
- The endpoint is synchronous. Creative/Flexible can take up to ~60s per image per #111's budget while holding `INFERENCE_LOCK`, which blocks other local inference for that long. Chosen because the ticket asks for the derivative asset in the response and a background job would have to duplicate the degraded-envelope contract across a second status endpoint. Flagged here, not silently shipped.
- `sharpen` and `smart_grain` default to 0 and `skin_detail` to 80. Magnific's own defaults for the two global sliders are not published in the research doc, so 0 (off) is the conservative choice, not a parity claim.

## 2026-09-26: Skin-enhance review-gate fixes (#112, map #73)

### Iteration Status: Done

**Why:** the driver returned 11 verified findings on the #112 backend half — one of them
disqualifying the feature. `make_diffbir_loader` built `DiffBIRFaceEngine(pipe, None)` while
`detect_faces` calls `self.face_helper.align_wrtk(...)`, so **every Creative and Flexible
request — the two modes carrying the whole value proposition, including all five Flexible
presets — could only ever answer `LOAD_FAILED`** on real hardware. The 54-test suite stayed
green because the DiffBIR loader test asserted plumbing (`pipe.enable_tiling` was called)
while the GFPGAN loader test actually called `engine.detect_faces(img)`.

**What changed:**

*Source — `backend/app/ml/skin_enhancer.py`*
1. **CRITICAL**: `make_diffbir_loader` now builds a real `FaceHelper` (`max_num=20`,
   `min_size=MIN_FACE_DIMENSION`, `detection_model="s3fd"`) and hands it to the adapter, the
   same configuration `make_gfpgan_loader` uses so a Faithful and a Creative run agree on what
   a face is. Comment records *why* (the DiffBIR pipeline takes no `face_helper=` kwarg, so
   there is nothing else to hand it) and that this is a second resident S3FD when both engines
   are loaded.
3. **HIGH**: deleted the `os.path.isfile(image_path)` + `open(image_path, "rb")` fallback in
   `_load_source_image`. `image_path` is caller-controlled, so that was an arbitrary local
   file read relative to the server CWD whose bytes then got re-uploaded to storage as a PNG
   derivative. Source bytes now come from `download_object` only, matching
   `app/routers/upscale.py`. Dropped the now-unused `import os`.
5. **MEDIUM**: `_usable_faces` clamps each detector box into the canvas and re-applies
   `MIN_FACE_DIMENSION` to the *clamped* box. S3FD returns `x0 = -4` / `y1 = height + 2` for
   tight crops and selfies; those were being discarded, producing a false `no_face_detected`
   400. A box with too little visible area, and one entirely off-canvas, are still dropped —
   the log line and the 400 detail were reworded to say "visible area after clamping".
6. **MEDIUM**: a failed `db.commit()` on the `MediaAsset` insert now returns
   `make_degraded_response(reason=LOAD_FAILED, ...)` instead of falling through to
   `COMPLETED`. The object is already in storage at that point, so `COMPLETED` handed the
   caller a filename and URL for an object with no catalog row and no `source_path` lineage.
7. **MEDIUM**: `INFERENCE_LOCK` scope narrowed. Source download/decode/cap moved **before**
   the lock; PNG encode, S3 upload and the catalog insert moved **after** it. Phases 2-7
   (parameter resolution, admission, lazy load, detection, restore, post-filters) stay inside,
   because `app/ml/guard.py`'s eviction invariant depends on it. Docstring records the split.
8. **LOW**: `_sanitize_output_stem` reduces the untrusted stem to `[A-Za-z0-9._-]`,
   `strip("._")` on both ends, falling back to `portrait`; a source of `..` no longer mints
   `skin_enhanced/.._<token>.png`.
9. **LOW**: `apply_texture_retention(source, restored, strength)` now takes both crops and
   computes `high = source - gaussian(source)`, adding `high * strength` to the restored
   crop. The old single-image version unsharp-masked the already-smoothed GAN output, which
   cannot recover pores, while its docstring claimed to. Call site passes the source crop;
   docstring rewritten to describe what it does.

*Source — `backend/app/routers/skin_enhance.py`*
2. **HIGH**: `image_path` no longer has its own slash-free regex. It reuses
   `SAFE_REFERENCE_PATTERN` imported from `app.routers.generate` (the pattern
   `/api/generate/video` already uses) with `_validate_safe_image_path` mirroring
   `_validate_safe_reference`'s rule list: `..`, a leading `/` and a backslash still refused.
   Subfolder keys (`upscaled/foo.png`, `uploads/portrait.png`) now pass, which the #111
   FileManager integration requires. One documented deviation: the shared pattern rejects
   spaces, and `app/routers/storage.py` sets an upload's key to `f"{folder}/{file.filename}"`,
   so `"my portrait.png"` is a real catalog row that this endpoint accepted before. Rather
   than copy a widened regex (the drift the reuse prevents) or regress that input, the check
   runs `SAFE_REFERENCE_PATTERN.match(value.replace(" ", ""))` — one source of truth for the
   character class, with the widening stated and tested.
4. **HIGH**: `_validate_slider` checks `math.isfinite` **before** the integrality test, with
   its own message. `int(float('nan'))` raises `ValueError` and `int(float('inf'))` raises
   `OverflowError`, so `NaN` / `Infinity` / `1e999` were unhandled 500s; they are now 400.

*Tests — `backend/tests/test_skin_enhancer.py`* (54 → 64)
- Extended `test_diffbir_loader_enables_tiling_and_offload` to fake `facexlib` and call
  `engine.detect_faces(img)`, and asserted the helper's `detection_model` / `min_size`; the
  CPU-only DiffBIR test got a `facexlib` fake too. **This is the test that let CRITICAL 1 ship.**
- `test_non_finite_slider_is_400_not_500` sends raw bodies (`NaN`, `Infinity`, `-Infinity`,
  `1e999`, `-1e999`) — `httpx` refuses to *encode* a non-finite float, so `json=` would have
  tested the client, not the route — and re-asserts the finite-fractional case separately.
- `test_subfolder_asset_key_is_accepted_and_traversal_is_still_refused`: `upscaled/foo.png`
  completes end-to-end; `../../etc/passwd`, `/etc/passwd`, `..\secret.png`, `upscaled/../..`
  all 400.
- `test_source_is_never_read_from_the_local_filesystem`: `chdir` to a tmp dir holding a real
  `portrait.png`, `download_object` stubbed to `None`, asserts 400 `source_not_found` and that
  nothing was written to storage.
- `TestFaceBoxClamping` (3): an overhanging box is clamped, reported clamped, and handed to
  the engine as the clamped crop; a box that clamps below the floor and a fully off-canvas box
  are both still dropped. The latter two passed before the fix too — they are guards that the
  clamp does not over-accept.
- `test_catalog_write_failure_degrades_and_withholds_the_filename`: `db.commit` raises →
  degraded `LOAD_FAILED`, **no `filename`, no `url`**, no new `MediaAsset`.
- `test_storage_io_runs_outside_the_inference_lock`: probes the lock from a second thread
  (an `RLock` re-enters on the same thread, so a same-thread probe passes vacuously) and
  asserts **both** states — held during `restore_face`, not held during `upload_object` — so
  the assertion cannot pass by the probe being broken.
- `test_output_stem_is_sanitised`: 9 stems including `..`, `.`, `...`, `$pecial!`, a spaced
  name and a hidden file.
- Texture retention: `test_texture_retention_restores_high_frequency_detail` (which asserted
  more high-frequency energy than its own input — unachievable for a real high-pass, which
  doubles the band) replaced by two tests: a blurred base must recover the source's texture,
  and a **flat** base must come out textured — unsharp-masking a flat base can only return
  flat, so any texture in the output came from the source crop.
- `test_output_key_shape_and_lineage` now expects `my_portrait_` in the key (sanitiser) and
  still asserts the `source_path` lineage is the spaced original.
- Deleted `assert "enhance_skin" == "enhance_skin"`; the rest of that test is unchanged.

*Tests — `backend/tests/test_localml_scaffold.py`*
- `test_pinned_roster_loaded_by_default` now asserts per-model metadata for `gfpgan`
  (image / fp32 / 1.5 GB / **Apache-2.0**) and `diffbir` (image / fp16 / 8.0 GB /
  **Apache-2.0**), so the license gate is checked where the roster is read, not only in the
  skin-enhance suite. The roster's exactness was not relaxed.

**Verified (TDD, red before green for every source fix):**
- Batch 1 red: `4 failed, 2 passed` — `assert None is not None` on `engine.face_helper`,
  `ValueError: cannot convert float NaN to integer` escaping the endpoint,
  `400 == 200` for `upscaled/foo.png`, and `200 == 400` because the local file *was* read
  (degraded `no_gpu` instead of a 400). Green after: 57 passed.
- Batch 2 red: `7 failed, 57 passed` — 3 × `TypeError: apply_texture_retention() takes 2
  positional arguments but 3 were given`, `no_face_detected` 400 for an overhanging box,
  `assert 'COMPLETED' != 'COMPLETED'` on a raised commit, `the storage upload must not run
  while INFERENCE_LOCK is held`, and `'..' produced 'skin_enhanced/.._5a6427bce4f6.png'`.
  In that same red run the lock test's `during_inference is True` assertion already passed,
  which is what proves the probe is not vacuous. Green after: 64 passed.
- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` → **559 passed, 2 skipped,
  0 failed** in 204.74s (final run, re-run after the last two edits). Pre-change baseline
  re-measured on the same tree: **549 passed, 2 skipped** in 217.25s. +10 = the 10 tests added; nothing removed. Same 2 skips
  (`test_semantic_search`, needs the fastembed model) and the same 3 pre-existing warnings
  (httpx/starlette deprecation + 2 duplicate-operation-ID warnings from `tasks.py`, already in
  TECH_DEBT.md). No new warnings.
- `cd frontend && npx tsc --noEmit` → exit 0, clean (no frontend file touched).
- `cd frontend && npx tsx --test src/utils/*.test.ts` → 62 tests, 62 pass, 0 fail.
- No `torch` / `diffusers` / `gfpgan` / `facexlib` in `.venv`; the suite is green without them.

**Not done / visible:**
- `image_path` spaces are still accepted here but refused by `/api/generate/video`, which
  shares the pattern. Making the *shared* validator accept a space is a change to the video
  route's contract and belongs in its own ticket; widening it there is a one-line follow-on
  to `_is_safe_image_path_chars`.
- The DiffBIR loader now holds a second resident S3FD when both skin engines are loaded
  (1.5 GB GFPGAN tier + 8 GB DiffBIR). Eviction is the registry's job and the VRAM guard
  admits against the 8 GB figure either way; if a host ever runs both, the honest fix is a
  shared detector handle in the registry, not a smaller number.
- Real-GPU behaviour of both engines is still unverified here; the loader tests exercise the
  adapters with fake modules, and `detect_faces` is now called for both.

## 2026-09-26: CodeRabbit review fixes on PR #138 (branch `t3code/f166906d`)

CodeRabbit left 7 inline comments on the PR. **4 applied, 3 deliberately parked** (no code, no
comment, no dependency added for them; reported to the human separately). Nothing committed,
nothing pushed, no GitHub access.

**APPLY 1 — `backend/app/ml/audio.py:184` — CWD-relative reference was a local file read (CWE-22)**
- Finding verified against the code: `reference` arrives from the `/api/generate/audio` query
  string, `_validate_safe_reference` blocks `..` / leading `/` / backslashes, and the old
  `os.path.isfile(reference)` + `open(reference, "rb")` fallback therefore accepted `.env` and
  `app/config.py` — both real files relative to the server's CWD — and re-uploaded their bytes
  to storage as a WAV derivative.
- Fix: removed the local-filesystem fallback. `download_object(reference)` is the only source;
  a miss raises the 400 (`reference_not_found: … was not found in storage.`), the same
  storage-only rule `skin_enhancer._load_source_image` uses and the upscale router already used.
  The video-refusal/HTTPException-400 behaviour ahead of it is unchanged. `os` is still imported
  for the temp-file cleanup at `audio.py:278`/`:312`.
- Test: `test_localml_audio.py::TestFix3ReferenceResolutionAndValidation::test_cwd_relative_reference_is_never_read_from_disk`
  — `monkeypatch.chdir(tmp_path)` with `.env` and `app/config.py` created under it, asserts 400
  for both plus nothing uploaded and no `MediaAsset`. Added the module-level `NO_GPU` guard dict
  (same shape as `tests/test_skin_enhancer.py`) so the test cannot depend on the host either.

**APPLY 2 — `backend/app/ml/video.py:343` — upload/commit failure still reported COMPLETED**
- Finding verified: `if upload_success and db is not None:` skipped the catalog insert on upload
  failure and then returned `status: "COMPLETED"` with a real `filename` and `""` as the url;
  `process_gpu_task` marked the `Task` COMPLETED and published a terminal COMPLETED event, so
  `GenerationPanel` rendered "Video uploaded: …" for an object that was never stored. The
  `db.commit()` failure was logged and swallowed with the same result.
- Fix: `upload_object` returning `False` now returns
  `make_degraded_response(reason=DegradedReason.LOAD_FAILED.value, message="Failed to upload
  generated video to storage", model_id="svd").model_dump()` **before** the `if db is not None:`
  block, and a failed `db.commit()` returns the same envelope with the exception text. Video now
  matches `run_local_audio_generation`, `run_local_image_generation` and `run_skin_enhancement`.
  `DegradedReason` / `make_degraded_response` were **already imported** at `video.py:27-30`, so
  the reviewer's "make sure they are imported" needed no change.
- Tests: `test_localml_video.py::TestVideoPipelineExecution::test_upload_failure_returns_degraded_not_completed`
  and `::test_catalog_commit_failure_returns_degraded_not_completed` — the first stubs
  `app.ml.video.upload_object` to return `False`, the second makes `db.commit()` raise; both
  assert `degraded is True`, `reason == "load_failed"`, `status != "COMPLETED"`, no `filename`
  key, and no `MediaAsset` row.

**APPLY 3 — `tests/test_generate_real_api.py`, `tests/test_elevenlabs_generate.py` — host-dependent assertions**
- Finding verified: both tests asserted a degraded `no_gpu` result without stubbing
  `vram_guard.get_gpu_info`, so on a CUDA host the guard admits the model and the loader fetches
  real XTTS/FLUX weights. Proven load-bearing with a throwaway test (since deleted): with
  `get_gpu_info` stubbed to a 24 GB RTX 4090 and `model_registry.load_model` replaced by a
  raiser, `POST /api/generate/audio` answers `reason: "load_failed"` — the guard was passed and
  the loader reached, so the un-pinned assertion would fail on such a host.
- Fix: added the `NO_GPU` dict and one `monkeypatch.setattr(vram_guard, "get_gpu_info", …)` in
  each test, before the audio call and before both the audio and image calls respectively.
  Matches `tests/test_localml_image.py` / `tests/test_skin_enhancer.py`. No other restructuring.

**APPLY 4 — `frontend/src/components/PlayersPanel.tsx:57` — `ws.addMarker` does not exist in wavesurfer v7**
- Finding verified against the installed package: `wavesurfer.js` 7.12.11,
  `WaveSurfer.prototype.addMarker` and `clearMarkers` are both `undefined`. `ws.clearMarkers?.()`
  was a silent no-op, `ws.addMarker(...)` threw `TypeError`, and the surrounding `try/catch`
  swallowed it into `console.warn` — every voice-clone marker was dropped from the waveform and
  only the fuchsia badge list showed anything.
- Fix: `applyMarkers(regions, markers)` now takes the Regions plugin instance, calls
  `regions.clearRegions()` and `regions.addRegion({ start: m.time, content: m.label,
  color: '#f43f5e', drag: false, resize: false })` — a region with no `end` renders as a
  vertical marker line. `initWaveSurfer` registers the plugin:
  `wsRegionsRef.current = ws.registerPlugin(RegionsPlugin.create())`, following the file's
  existing dynamic-import convention for `wavesurfer.js`. Cleanup nulls the ref alongside
  `ws.destroy()`.
- Import path **verified, not guessed**: the package declares `"./dist/plugins/*.js"` and
  `"./dist/plugins/*.esm.js"` in its own `exports` map, so
  `wavesurfer.js/dist/plugins/regions.esm.js` resolves. `regions.d.ts` ships a **default**
  export only, so the import is `{ default: RegionsPlugin }` — a named `{ RegionsPlugin }`
  destructure would be `undefined` at runtime. Checked three ways: `tsc --noEmit` exit 0; a
  probe file asserting `addRegion({ start: 'x' })` produced two real `TS2322` errors (so the
  types resolved, not `any`); and `node --input-type=module` imported the file and reported
  `default: function` with `create`/`clearRegions`/`addRegion` present.

**Parked, not touched (per instruction):** `celery_app.py` `task_acks_late` (architecture
decision), and in `skin_enhancer.py` both the GFPGAN/facexlib API usage and the
`DiffBIRPipeline` call (each needs a new dependency / an architecture decision).

**Verified (TDD — both behaviour changes genuinely red first):**
- Red for APPLY 1: `AssertionError: Expected 400 for CWD-relative reference '.env'`,
  `assert 200 == 400` — the request reached the VRAM guard (`Local audio inference refused:
  no_gpu`), which is only possible if the file was read off disk.
- Red for APPLY 2: 2 failed. The upload case returned
  `{'status': 'COMPLETED', 'type': 'video', 'filename': 'gen_video_<ns>.mp4', 'url': '', …}`
  and failed `assert None is True` on `degraded`; the commit case logged
  `Failed to save generated video asset: catalog write failed` and still returned
  `status: COMPLETED` with a real `url`, also failing `assert None is True` on `degraded`.
  Green for all three after the fixes: `3 passed`.
- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` → **562 passed, 2 skipped,
  0 failed** in 205.78s. Pre-change baseline re-measured on this same tree: **559 passed,
  2 skipped** in 215.12s. +3 = the 3 tests added by APPLY 1 and APPLY 2; nothing removed, so
  the count does not drop below 559. Same 2 skips (`test_semantic_search`, needs the fastembed
  model) and the same 3 pre-existing warnings (httpx/starlette deprecation + 2 duplicate
  operation-ID warnings from `tasks.py`, already in TECH_DEBT.md). No new warnings.
- `cd frontend && npx tsc --noEmit` → exit 0, clean.
- `cd frontend && npx tsx --test src/utils/*.test.ts` → 62 tests, 62 pass, 0 fail.
- `npx next lint` not run: the repo has no ESLint config, as recorded previously.

**Not done / visible:**
- APPLY 4 is verified by typecheck and by resolving the package's real exports, not by a
  component test — the frontend suite is `src/utils/*.test.ts` only and has no React renderer,
  so asserting the marker line is drawn would mean adding a test harness, which is out of scope
  for a review-response pass.
- `run_local_audio_generation`'s docstring step 4 mentions the upload; the storage-only
  reference rule is now documented at the resolution site rather than in the numbered steps.
- Real-GPU behaviour of any of this is still unverified here; the new tests pin the guard
  explicitly rather than assuming a device.

## 2026-09-27: Fix the skin-enhance engines (#138 review, map #73)

### Status: Review

### The defect
`backend/app/ml/skin_enhancer.py` wired both engines to APIs that do not exist, so every mode
of `POST /api/skin-enhance` was non-functional on real hardware. The 64 tests passed because each
one injected a fake `gfpgan` / `facexlib` / `diffusers` module that defined exactly the symbols the
production code referenced — the fakes were derived from the call sites, so the suite asserted the
invented API against itself. Eight invented symbols:

| reference in #112 | reality |
|---|---|
| `facexlib.face_helper.FaceHelper` | class does not exist in facexlib 0.3.0 |
| `FaceHelper.align_wrtk(img)` | no `align_wrtk` on any facexlib class |
| `FaceHelper(detection_model="s3fd")` | `init_detection_model` implements only `retinaface_resnet50` / `retinaface_mobile0.25`; `s3fd` raises `NotImplementedError` |
| `GFPGANer(..., face_helper=helper)` | no such kwarg; the helper is built internally and reachable as `restorer.face_helper` |
| `restorer.enhance_model()` / `restorer.to("cpu")` | neither exists; `GFPGANer` is a plain class and takes `device=` |
| `gfpgan.GFPGAN_VERSION_1_3 / _1_4` | gfpgan 1.3.8 exports no such constants; `model_path` is a path or https URL |
| `restorer.enhance(crop_pil, ...)` → PIL | `enhance` takes a **BGR ndarray** and returns the 3-tuple `(cropped_faces, restored_faces, restored_img)` with `restored_img` a **BGR ndarray** |
| `from diffusers import DiffBIRPipeline` | DiffBIR is not a diffusers pipeline and is not on PyPI |

### Changes
- **`app/ml/skin_enhancer.py`** — `GFPGANFaceEngine` rebuilt on the real `GFPGANer`:
  `GFPGANer(model_path=…, upscale=1, arch='clean', channel_multiplier=2, bg_upsampler=None, device=torch.device(…))`;
  `detect_faces` drives the restorer's own `FaceRestoreHelper` (`clean_all` → `read_image(BGR)` →
  `get_face_landmarks_5` → `det_faces`), preserving detect-before-forward-pass; `restore_face`
  converts PIL↔BGR and handles the real 3-tuple, refusing an empty `cropped_faces` or a `None`
  `restored_img` rather than reporting an unrestored crop as a restoration. Detector is
  `retinaface_resnet50` — GFPGANer hardcodes it and offers no supported override, and DiffBIR's
  own `UnAlignedBFRInferenceLoop` uses the same one; documented rather than silently assumed.
- **`app/ml/skin_enhancer.py`** — `DiffBIRFaceEngine` is now a subprocess integration. `build_diffbir_argv`
  is a pure function so the argv is assertable in CI; `restore_face` stages the crop as a real PNG
  in a temp dir, runs `<python> <repo>/inference.py …` with `cwd=<repo>`, and reads `<stem>_0.png`
  back. Timeout mandatory (it runs inside `INFERENCE_LOCK`). No `diffusers` import anywhere.
- **`app/config.py`** — `DIFFBIR_REPO_PATH`, `DIFFBIR_PYTHON`, `DIFFBIR_TIMEOUT_SECONDS`,
  `GFPGAN_MODEL_PATH`. Unset/wrong `DIFFBIR_REPO_PATH` → `ValueError` naming the setting and the
  clone recipe → the existing `LOAD_FAILED` envelope at HTTP 200. Nothing is fabricated.
- **`app/ml/registry.py`** — GFPGAN's `approx_vram_gb` comment corrected (the resident models are the
  generator + `retinaface_resnet50` + parsenet, not "S3FD"; v1.4 → v1.2-clean, which is what the
  loader now names). DiffBIR's 8 GB comment made honest: published for *tiled whole-image*
  inference; running per face crop should be smaller, that is our inference, and it is unverified
  without a GPU. The number stays 8.0 (upstream's, and the conservative direction).
- **`backend/requirements.txt`** — adds `gfpgan>=1.3.8`, `facexlib>=0.3.0`, `basicsr>=1.4.2`.
  **DiffBIR is deliberately not listed**: not on PyPI. Instead a commented `git clone --recursive` +
  env-var recipe, and its extra deps (`omegaconf`, `accelerate`, `einops`, `timm`, `torchsde`,
  `pytorch-lightning`, `lpips`, `xformers`, …), noted as belonging in a separate venv because of
  its pinned `torch==2.2.2+cu118`.
- **`tests/test_skin_engine_contracts.py`** (new, 43 tests) — see below.
- **`tests/test_skin_enhancer.py`** — `TestLoaderFactories` rewritten against the contract mirrors;
  the two DiffBIR-pipeline tests deleted (they asserted on a mock's call record for a class that
  does not exist). `MagicMock` import dropped, now unused.

### New contract tests, and what each would have caught
1. `TestNoInventedApiSymbols::test_production_module_names_no_symbol_absent_upstream` — tokenised
   denylist regex scan of the production module. Catches **all eight** rows in the table above.
2. `::test_the_denylist_would_catch_the_old_implementation` — points the same denylist at the
   pre-fix loader, requires ≥7 hits. Stops the guard rotting into a no-op.
3. `::test_gfpgan_import_is_confined_to_the_loader_closure` / `::test_heavy_imports_stay_inside_a_nested_def`
   — the app must still boot with no torch. (Both already passed pre-change; kept as regression guards.)
4. `TestRealGfpganApiContract` (7 tests, `importorskip`) — introspects the installed `GFPGANer`:
   constructor kwargs, `enhance` kwargs, absence of `enhance_model`/`.to`, absence of
   `GFPGAN_VERSION_*`, that `model_path` still special-cases `https://`, and that
   `arch`/`channel_multiplier`/model URL are mutually consistent. Catches the `face_helper=` kwarg,
   the offload API, the version-constant import, and a `clean`-arch/`GFPGANv1`-weights mismatch that
   would raise `load_state_dict(strict=True)` on the first real load.
5. `TestRealFacexlibApiContract` (6 tests, `importorskip`) — `FaceRestoreHelper` has
   `read_image`/`get_face_landmarks_5`/`align_warp_face`/`get_inverse_affine`/`add_restored_face`/
   `paste_faces_to_input_image`/`clean_all` and has **no** `align_wrtk`; `get_face_landmarks_5`
   takes our kwargs; `det_faces` is the public box list and is reset by `clean_all`;
   `init_detection_model`'s source implements exactly the two retinaface names and raises
   `NotImplementedError`; the loader only names one of those two. Catches `align_wrtk`,
   `FaceHelper`, and `detection_model="s3fd"`.
6. `TestSkipIsLoud::test_records_whether_real_apis_were_introspected` — a green run in which the
   real-API tests skipped is not a green run; this makes the skip explicit with instructions.
7. `TestStubSignaturesMirrorRealApi` (5 tests) — the CI stubs are *contract mirrors*: their
   `__init__`/`enhance` parameter lists are compared against signature literals copied out of
   gfpgan 1.3.8, and against the real classes wherever they are importable. Prevents the stubs from
   ever again being the authority on what the API looks like.
8. `TestDiffBIRArgvContract` (14 tests) — the argv is asserted directly and parsed through a mirror
   of the real `parse_args`: `--captioner none`, `--task unaligned_face`, `--version v2.1`,
   `--upscale 1`, `--cfg_scale` (mapped from `skin_detail`, 4 slider positions), `--noise_aug`
   (mapped from `condition_noise`, 5 values), `--steps`, `--seed 231`, `--device/--precision`,
   `--n_samples 1`, the verbatim `--pos_prompt` for **all five presets**, upstream's
   `DEFAULT_NEG_PROMPT`, and that the tiled flags are *bare* (`store_true`). Catches the
   `DiffBIRPipeline` fiction, a missing flag, and `--cleaner_tiled true`.
9. `TestDiffBIRRepoPathContract` (4 tests) — unset / non-existent / no-`inference.py` all raise
   naming the setting and the path; end-to-end, an unset path gives HTTP 200 `LOAD_FAILED` naming
   `DIFFBIR_REPO_PATH` with no `filename` and nothing written to storage.
10. `TestDiffBIRStagingIntegration` (6 tests) — crop is on disk under `--input` *before* the call,
    `cwd` is the repo root, timeout is passed, `<stem>_0.png` is read back; non-zero exit and a
    missing output file are both errors, never the source crop passed through. Two of these drive
    the **whole route** through the real `DiffBIRFaceEngine` with only `subprocess.run` replaced —
    the only place a mismatch between `resolve_engine_params` and `build_diffbir_argv` can surface.
11. `TestGfpganRestoreHonesty` (4 tests) + `TestPilBgrConversion` (3 tests) — the 3-tuple, the
    empty-restore refusal, the `None` refusal, the wrong-type refusal, and an exact BGR↔RGB round
    trip including C-contiguity (a negative-stride view is rejected by `Image.fromarray`).

### Verification (actual numbers)
- `cd backend && .venv/bin/python -m pytest tests/test_skin_engine_contracts.py -q -p no:cacheprovider`
  against the **old** production code: **31 failed, 3 passed, 16 skipped, 1 error**. The headline
  failure listed all eight invented symbols by name. Red confirmed before the rewrite, not assumed.
- Same file after the rewrite: **43 passed, 16 skipped** (the 16 are the real-API
  introspections plus the two mirror-vs-real diffs, all `importorskip`-gated).
- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` → **608 passed, 18 skipped,
  0 failed** in 209.35s. Pre-change baseline on this tree: **562 passed, 2 skipped**. +46 net
  (43 new contract tests, 3 net new loader tests). Same 2 pre-existing skips
  (`test_semantic_search`, needs the fastembed model) and the same 3 pre-existing warnings
  (httpx/starlette deprecation + 2 duplicate operation-ID warnings from `tasks.py`, already in
  TECH_DEBT.md). No new warnings.
- `cd frontend && npx tsc --noEmit` → exit 0, clean. No frontend file was touched.
- `npx next lint` not run: the repo has no ESLint config, as recorded previously. Not added.
- torch / gfpgan / facexlib were **not** installed into `backend/.venv`. The probe venv at
  `/tmp/opencode/probe` was read only.

### Non-vacuity proof for the skipped introspection tests
Because `gfpgan` cannot be imported without torch, the **real** class bodies were extracted from
`/tmp/opencode/probe/.../gfpgan/utils.py` and `facexlib/utils/face_restoration_helper.py` with
`ast.parse` + `compile` (heavy globals stubbed) and the same assertions were run against them:
- old assumptions → **all fail**: no `face_helper` kwarg; no `enhance_model`; no `.to`;
  no `align_wrtk`; `init_detection_model('s3fd')` → `NotImplementedError: s3fd is not implemented.`;
  no `GFPGAN_VERSION` in the module.
- new assumptions → **all pass**: the six constructor kwargs, the five `enhance` kwargs, the seven
  helper methods with `align_wrtk` absent, exactly `retinaface_resnet50`/`retinaface_mobile0.25`
  supported, `startswith('https://')` still in `GFPGANer.__init__`.

### Non-vacuity proof for the argv
`parse_args`, `DEFAULT_POS_PROMPT` and `DEFAULT_NEG_PROMPT` were extracted from the real
`/tmp/opencode/DiffBIR/inference.py` (commit `5c2d6c1`) and our argv was run through the **real**
parser for all five presets: all five parse, and all 14 checked fields match. Our
`DIFFBIR_NEGATIVE_PROMPT` is byte-identical to upstream's `DEFAULT_NEG_PROMPT`. Separately
confirmed: bare `--cleaner_tiled --cldm_tiled` is **accepted**; `--cleaner_tiled true
--cldm_tiled true` is **rejected** with `error: unrecognized arguments: true true` (exit 2) — so
the task sketch's `--cleaner_tiled true` form would have broken every Creative/Flexible request
after five model loads, and we deliberately do not use it.

### Not done / visible
- **The UI still offers Creative and Flexible on a deployment with no `DIFFBIR_REPO_PATH`**, where
  every such request degrades with a message about an env var. Surfacing
  `diffbir_repo_configured` on `GET /api/skin-enhance/presets` (and greying the mode switch) is the
  fix; it touches the frontend panel, so it is left as a follow-up rather than smuggled into a
  correctness pass.
- **One subprocess per face.** An N-face group shot pays N DiffBIR model loads. Batching all crops
  into a single staging directory and invoking once would fix it, at the cost of the executor's
  per-face failure isolation. Documented in the class docstring; not done.
- **`retinaface_mobile0.25` is not used.** facexlib supports it and it would save ~50 MB and some
  time on the Faithful tier, but reaching it means assigning over `restorer.face_helper` after
  construction, re-deriving the `face_size`/`crop_ratio`/`upscale_factor`/`use_parse` wiring that
  `enhance()`'s paste-back geometry depends on. Reusing GFPGANer's own helper is the lower-risk
  choice and agrees with DiffBIR's own detector. Deviation from the brief, deliberate and recorded.
- **Nothing here was run on a GPU.** See LEARNINGS.md, "A note on what is still unverified", for
  the itemised list — GFPGAN output quality and identity shift, the VRAM footprint of either
  engine, the `--noise_aug` placement of each preset, the ≤60s Creative/Flexible budget beyond one
  face, detector agreement between our box and DiffBIR's, and that the v1.2-clean checkpoint loads
  at runtime rather than only by construction.

## 2026-09-27: One DiffBIR process per request, not per face (#138 follow-up, map #73)

### Status: Review

### The defect
`run_skin_enhancement` called `engine.restore_face(crop, …)` once per detected face. For GFPGAN
that is right: `model_registry` caches the loaded instance, so its Nth face is one forward pass
on resident weights. For DiffBIR a call is a **process**, and the process is what loads the
models — SwinIR ×2, ControlLDM, SD 2.1 and the diffusion schedule. So a 6-face group shot paid
the whole load six times over, against the ~60s-per-image target #111 states for
Creative/Flexible. Nothing required this: `--input` is a *folder* (`load_lq` globs it with
`sorted(os.listdir(...))` over `.png/.jpg/.jpeg`) and `UnAlignedBFRInferenceLoop.save` writes one
`<stem>_0.png` per input. The per-face loop was an accident of the executor, not a constraint.

### Changes
- **`app/ml/skin_enhancer.py` — `DiffBIRFaceEngine.restore_faces(crops, **params) -> list[Image]`**
  stages every crop into ONE temp input dir as a real PNG with a unique
  `face_<run>_<0000..>` stem (one `uuid4` token for the run, zero-padded index so upstream's
  `sorted()` order is the input order), runs the subprocess once, and reads `<stem>_0.png` per
  stem. `cwd`-is-repo-root, the mandatory timeout, `build_diffbir_argv`, the `TimeoutExpired` →
  `RuntimeError` and non-zero-exit → `RuntimeError`-with-stderr paths are all unchanged.
  Parameter validation moved to `_validate_restore_params` and is shared.
  **All-or-nothing**: one missing output file raises, naming the absent file and
  "N of the M staged face crop(s)". A short list is worse than an error here — the executor pairs
  results with boxes positionally, so a list missing its first entry pastes face 2's restoration
  onto face 1's box and reports success.
- **`app/ml/skin_enhancer.py` — `restore_face` is now a one-line delegation**
  (`self.restore_faces([crop], **params)[0]`) rather than a second copy of the staging code. Two
  copies of that block is exactly how one of them would drift back to per-face subprocesses. The
  single-crop contract is still pinned from the outside by `TestDiffBIRStagingIntegration`.
- **`app/ml/skin_enhancer.py` — executor dispatch.** The crops are built once
  (`[image.crop(box) for box in usable]`), and an engine offering `restore_faces` is asked for the
  whole request in one call. An engine without it (GFPGAN) keeps the per-face loop verbatim,
  including the `Face {index}/{total}` log line and its `Face {index} of {total} failed` envelope.
  Batch failures degrade the whole request to `LOAD_FAILED` with the same envelope shape; a
  duck-typed engine returning the wrong number of results is refused rather than guessed at.
  The resize-and-paste loop is now shared by both shapes, so `faces_enhanced` / `face_boxes` /
  `faces_skipped`, the background-untouched guarantee and the per-face resize warning are
  identical either way. Nothing outside the face boxes is ever handed to an engine in either
  shape: only crops are staged, never the image.
- **Comments corrected.** The `DiffBIRFaceEngine` docstring now says batching amortises the model
  load across the faces of one request and that **no wall-clock number for Creative/Flexible has
  ever been measured here because there is no GPU in CI** — #111's ~60s is a design target the
  engine was chosen against, not a benchmark. Same correction on `DIFFBIR_INFERENCE_STEPS` (was
  "the 10-step path is the one that fits the budget") and on the executor's phase-8 docstring
  ("budgeted at up to 60s"). `GFPGANFaceEngine` gained the reason it has *no* `restore_faces`:
  its model is resident across calls, and `enhance()` re-detects inside the image it is given, so
  N crops as one image is a different operation, not a batched one.

### Tests (TDD: written first, watched red, then implemented)
Red before the change, on the new tests alone: **11 failed, 3 passed**
(`pytest tests/test_skin_engine_contracts.py::TestDiffBIRBatchRestore
tests/test_skin_enhancer.py::TestBatchRestoreDispatch`). The route-level failure was the defect
itself: `three faces cost 3 DiffBIR loads; batching is the whole point of restore_faces`.

`TestDiffBIRBatchRestore` (7 new, `tests/test_skin_engine_contracts.py`) — the stub stands in for
`inference.py`, reads the staging dir **as it found it** and writes one `<stem>_0.png` per input:
1. `test_four_crops_cost_exactly_one_subprocess_invocation` — 4 crops → exactly 1 process; all 4
   PNGs on disk under the single `--input` folder before the call, stems unique, `argv` has one
   `--input`/`--output` pair pointing at those folders, `cwd` = repo root, `timeout` = 300.0.
2. `test_results_come_back_in_the_order_the_crops_went_in` — each staged crop is a distinct solid
   colour, the stub writes outputs in **reverse** order and tags each with its own input's colour
   (`+1` per channel), so the test fails both if the read-back follows write order and if the
   results come back reversed.
3. `test_one_missing_output_file_fails_the_batch_rather_than_shortening_it` — one crop gets no
   output file; the error names `face_…_0000_0.png` and says "1 of the 4".
4. `test_restore_face_is_the_batch_of_one` — the single-crop path is still real: one process, one
   staged crop, same cwd, same result.
5. `test_an_empty_crop_list_costs_no_process_at_all` — 0 crops launches nothing.
6. `test_the_batch_still_refuses_missing_and_unexpected_parameters` — the four argv inputs are
   still required, an unknown key is still refused, and neither launches DiffBIR.
7. `test_a_group_shot_through_the_route_is_one_process` — the real adapter + the executor + the
   route, only `subprocess.run` replaced: 3 detected faces → **1** process, 3 staged crops, 3
   results, `faces_enhanced == 3`, `face_boxes` in detected order, every background pixel
   bit-identical, all 3 boxes visibly restored, `--cfg_scale` still carries the mapped slider value.

`TestBatchRestoreDispatch` (7 new, `tests/test_skin_enhancer.py`, on a new `FakeBatchFaceEngine`) —
1. `test_engine_with_restore_faces_is_asked_once_for_the_whole_request` — 1 batch call, 3 crops in
   it, `restore_face` never called.
2. `test_a_group_shot_reports_every_face_through_the_batch_path` — `faces_enhanced` 2,
   `faces_skipped` 1, boxes in order, creative params still forwarded.
3. `test_engine_without_restore_faces_keeps_the_per_face_loop` — **the GFPGAN path**, unchanged:
   3 `restore_face` calls, 3 crop sizes, same response.
4. `test_the_real_gfpgan_adapter_has_no_batch_entry_point` — the real classes, not the fakes:
   `GFPGANFaceEngine` has no `restore_faces`, `DiffBIRFaceEngine` has.
5. `test_a_failed_batch_degrades_the_whole_request_and_writes_nothing` — LOAD_FAILED at HTTP 200,
   the engine's own message, no filename/url, nothing in storage, no catalog row.
6. `test_a_batch_that_returns_fewer_images_than_crops_is_refused` — the executor's own guard, for
   a duck-typed engine that is not careful.
7. `test_the_batch_path_leaves_the_background_untouched` — #111 decision 4 under batching, and
   both boxes (not just the first) visibly restored, which is what a mis-paired list would break.

### Existing tests adjusted
- **`TestDiffBIRStagingIntegration::test_timeout_is_always_passed_so_a_hang_cannot_hold_the_inference_lock`**
  (only one). It did `inspect.getsource(DiffBIRFaceEngine.restore_face)` and asserted
  `"timeout=" in source`; `restore_face` is now a delegation, so the substring legitimately moved
  to `restore_faces`. It now inspects `restore_faces` (timeout present, `subprocess.run` present)
  **and** asserts `restore_face` contains no `subprocess.run(` of its own and does call
  `restore_faces(` — which keeps the intent (no unguarded subprocess on any path) and adds the
  delegation check. No other existing test needed changing: the batch seam is additive, and the
  per-face path is byte-for-byte the old one.

### Verification (actual numbers)
- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` → **622 passed, 18 skipped,
  0 failed** in 204.79s. Pre-change baseline on this tree: **608 passed, 18 skipped**. +14 net,
  exactly the 14 new tests; the 18 skips are the same ones (16 gfpgan/facexlib contract
  introspections, `TestSkipIsLoud`, `test_semantic_search` needs the fastembed model) and the 3
  warnings are the same pre-existing httpx/starlette + duplicate-operation-ID ones in TECH_DEBT.md.
- Skin files only: `pytest tests/test_skin_engine_contracts.py tests/test_skin_enhancer.py` →
  **124 passed, 16 skipped**.
- `cd frontend && npx tsc --noEmit` → exit 0. No frontend file was touched.
- `npx next lint` not run: the repo has no ESLint config, as recorded previously.
- torch / gfpgan / facexlib were **not** installed into `backend/.venv`; the 16 contract skips are
  intended and `TestSkipIsLoud` records them.

### Non-vacuity: the new tests were mutated, not just watched go green
- Return the results reversed → `test_results_come_back_in_the_order_the_crops_went_in` fails
  (`[(41, 61, 81), …] != [(11, 1, 1), …]`).
- Turn the missing-output raise into a silent short list →
  `test_one_missing_output_file_fails_the_batch_rather_than_shortening_it` fails, and only that one.
- Disable the executor's batch branch (`if False`) → 5 failures across both new classes, including
  the route-level one.
- Each mutation was reverted and the file verified byte-identical to the pre-mutation copy.

### Not done / visible
- **No wall-clock claim.** The model load is now paid once per request instead of once per face,
  which is a structural saving, not a number: how long one DiffBIR process takes for 1 crop or for
  6 has never been measured here, and the ≤60s in #111 stays a design target. Nothing in this pass
  produces a timing figure and none was invented.
- **Peak memory of a batched run is still inferred, not observed.** One process handles the folder
  sequentially (its `save()` is per input), so the "one crop resident" property should hold — but
  that is read off `save()`'s per-input contract, not watched, and it is what a real GPU run with
  6 faces would confirm or refute.
- **A batch failure is now all-or-nothing at the route level**: one bad crop out of six fails the
  whole request to `LOAD_FAILED`. That is the same trade the module already made for a single face
  (never fabricate, never partially report), and the per-face isolation the old docstring gave up
  is now actually given up rather than merely deferred.
- The UI still offers Creative/Flexible on a deployment with no `DIFFBIR_REPO_PATH`; surfacing
  `diffbir_repo_configured` on `GET /api/skin-enhance/presets` remains the open follow-up from the
  previous entry.

## 2026-09-28: Wayfinder Map #74 - Deep Parity: Background Remover

### Status: Done

### Changes & Verification:
- **Phase 1 (HITL): #115 - Decide quality bar, output formats, UX placement**
  - Human decided (grilling): library-only action entry (Media Library rows/cards, no editor tool until map #75); two tiers (rembg+u2net default "Fast", birefnet-general "Quality" toggle); PNG RGBA only; preview-before-accept with an additive derivative via `source_path` (original never mutated, re-run = sibling).
  - Recorded on #115, closed, appended to map #74.
- **Phase 1 (HITL): #117 - Prototype the remove-background UX with mask preview**
  - Built 3 structurally different variants behind `?variant=` on the existing Media Library page (slide-over panel / modal wizard / inline strip) in `frontend/src/components/bgremove-prototype/`, read-only stub, floating switcher, served over a Cloudflare quick tunnel for remote review.
  - Fix along the way: with no backend, FileManager's blocking "Communication error" panel hid the sample rows — the error panel now only shows when there are zero files, otherwise an amber "Backend unreachable - showing prototype sample assets" banner sits above the list.
  - Human picked **Variant C (inline strip)**; recorded, closed, appended to map. Prototype captured on throwaway branch `proto/117-bgremove-ux` (commit `3cbd3a8`), not on main.
- **Phase 2 (AFK): #116 - Build remove-background endpoint producing derivative asset**
  - `POST /api/bgremove` (+ `/presets`, `/tiers`, `/status/{task_id}`) in `backend/app/routers/bgremove.py`, pipeline in `backend/app/ml/bgremove.py`.
  - Fast tier caches the rembg ONNX session behind a lock; quality tier lazy-loads `ZhengPeng7/BiRefNet-general` through transformers and maps missing weights/deps to a typed `BgRemoveModelUnavailable` -> HTTP 200 degraded envelope (`reason=load_failed`).
  - RGBA PNG derivative under `bg_removed/<stem>_<12hex>.png` with `source_path` lineage; blob deleted if the catalog commit fails; oversize inputs capped at 8192px; `Task.name` static `"bgremove"`; progress frames on Redis `task_updates`.
  - Review gate: first pass **REQUEST-CHANGES** (2 blockers, 6 should-fix, 4 nits) -> all 12 fixed -> re-review **APPROVE**.
  - Commit `b2cbe82` on branch `wf/74-116-bgremove-endpoint`.

### Overall Verification:
- `cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider` -> **650 passed, 18 skipped** (baseline 622/18; 28 new offline tests, no model downloads or network).
- `compileall app tests` clean. Frontend untouched by #116; `npx tsc --noEmit` was clean while the prototype was on the branch.

## 2026-09-28: Wayfinder Map #73 - Skin Enhancer UI (#137)

### Status: Done

### Changes & Verification:
- **#137 - Build the Skin Enhancer UI from the approved VariantD composite**
  - `frontend/src/utils/skin.ts` (+ `skin.test.ts`): pure contract the panel sits on — mode list with engine/budget per mode, the five verbatim Magnific presets, slider bounds, the mode-aware skin_detail meaning (post-filter vs DiffBIR guidance), payload construction, slug-based failure parsing. `isImageFile` exported from `upscale.ts` so the two action gates cannot disagree.
  - `frontend/src/utils/api.ts`: `startSkinEnhance` (rethrows the server detail so the panel shows `no_face_detected:`-style slugs), `fetchSkinEnhanceSurface` (mode rows read engine/budget from `GET /api/skin-enhance/presets` instead of a second hardcoded copy).
  - `frontend/src/store/useStore.ts`: `skinTarget` slice, deliberately not persisted — the panel is an overlay, not a navigation destination.
  - `frontend/src/components/skin-enhancer/`: `SkinEnhancerPanel` (overlay orchestration, sequential run loop, surface fetch fallback), `SourceStrip` (select vs focus, explicit per-thumb x), `CompareCanvas` (pointer + keyboard split, running/focused status, honest "Enhanced N faces" chip), `ControlRail` (engine+budget mode rows, amber honest-knob box, run button/error), `ResultsTray` (amber degraded card, rose failed card with slug).
  - `FileManager.tsx`: per-asset "Skin" icon button, images only (`disabled` on non-images), inserted after the existing Upscale action; `page.tsx` mounts `{skinTarget && <SkinEnhancerPanel />}`.
  - `frontend/e2e/10-skin-enhancer.spec.ts` (+ `test:e2e:skin` script): 3 tests — action/panel/mode-row/preset gating, a real two-source run, and a `page.route`-intercepted completed run through `BeforeAfterModal`.
- Decisions carried, none re-litigated: #111 mode/slide/preset/degraded contract, #113 selected≠focused and explicit x, images only, no sidebar tab.
- **Deviation (reported):** the endpoint is synchronous with no per-face progress stream, so the composite's "Enhancing face 2 of 3" cannot be shown without inventing data. A running row states the engine and stated budget ("Enhancing · GFPGAN · ~5s/image") and the face count appears only when the response lands.

### Overall Verification:
- `cd backend && /home/parth/projects/FusionClip/.venv/bin/python -m pytest tests/ -q` -> **653 passed, 16 skipped** (skips are gfpgan/facexlib/facex introspection, no GPU host).
- `cd frontend && npx tsc --noEmit` clean; `npx tsx --test src/utils/*.test.ts` -> **89 pass, 0 fail** (27 new skin tests, written red first).
- E2E over the no-Docker stack (moto :9000 + uvicorn :8001 sqlite + next dev :3001, `E2E_BASE_URL`/`E2E_API_URL`): `e2e/10-skin-enhancer.spec.ts` -> **3 passed**; `e2e/09-upscaler.spec.ts` -> passed; `e2e/01-smoke-navigation.spec.ts` -> 2 failed **both before and after** the change (verified against a stashed clean tree), pre-existing and unrelated.
- `npm run lint` not run: the repo has no lint script wired (`next lint` prompts interactively) and no ESLint config; none was created.
