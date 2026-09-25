# Learnings & Edge Cases

## 2026-09-23: Trust & Integrity Architecture (Map #67)

### 1. SQLite vs PostgreSQL Vector Search in Tests
- `pgvector.sqlalchemy.Vector` stores raw data in SQLite during testing, but PostgreSQL's native vector distance operator `<->` or `<=>` fails in SQLite syntax (`near "->": syntax error`).
- Architecture pattern: check `db.bind.dialect.name == "postgresql"`. If true, execute native vector order in SQL (`MediaAsset.embedding.cosine_distance(...)`). If in SQLite/tests, compute cosine distance ranking across assets with embeddings in Python. This preserves fast in-memory testing without requiring a live Postgres instance while testing true semantic ranking.

### 2. FastEmbed vs PyTorch for CPU Embeddings
- `sentence-transformers` via PyTorch requires downloading over 2GB of CUDA wheels if unpinned.
- `fastembed` runs the exact same `sentence-transformers/all-MiniLM-L6-v2` ONNX model (~90MB) on CPU in ~1ms per query without heavy CUDA dependencies, making it optimal for local and CI environments.

### 3. Zustand Persistence Leaks
- Merely updating `partialize` to exclude a key does not clean up data already stored on existing users' disks.
- When removing a key from localStorage persistence (like `colabTunnel`), bump the zustand store version and supply a migration function that deletes `persistedState.colabTunnel`.

### 4. FastAPI Validation Status Codes
- Pydantic/FastAPI query param validation returns 422 Unprocessable Entity by default.
- When an API contract or ticket specifies 400 Bad Request for unknown pipeline types, explicit validation raising `HTTPException(status_code=400, detail=...)` must be performed in the route handler.

## 2026-09-23: Real API Generation (Map #68)

### 5. Google Gemini Key Migration & Nano Banana Image Models
- Google Gemini deprecated standard API keys in September 2026. Unrestricted standard keys fail with HTTP 401 until rotated to auth keys or scoped to the Gemini API.
- Google Imagen endpoints are completely shut down on the Gemini developer API. Image generation is served by Nano Banana (`gemini-3.1-flash-image`), which emits base64 `inlineData` with automatic Google SynthID digital watermarking. Diffusion sampling parameters (`steps`, `scale`) do not apply to Gemini and should only be exposed for local/Colab diffusion workflows.

### 6. ElevenLabs Binary Responses vs Error Envelopes
- Successful ElevenLabs TTS and SFX endpoints return raw binary audio streams (`audio/mpeg`), while errors return JSON with structured `detail` envelopes. The client must never attempt to JSON-parse successful binary streams, and must extract error messages from `detail.message` or `detail` arrays on failure.

### 7. Frontend Error Payload Normalization
- FastAPI validation errors (422) return `detail` as an array of error objects, whereas custom HTTPExceptions often return string `detail`. The frontend API client must inspect `typeof detail` and JSON-stringify objects/arrays to avoid rendering `[object Object]` in user-facing error banners.

## 2026-09-23: Colab Real Inference & Execution Harness (Map #69)

### 8. Colab Worker Pydantic v2 Null-Field Validation
- In Pydantic v2, defining a model field as `output: dict = None` does not make `None` valid in request bodies if `Optional[dict]` is not used. Incoming JSON with `{"output": null, "error": null}` raises a 422 Unprocessable Entity. Model fields receiving optional status payloads must always be explicitly typed `Optional[T] = None`.

### 9. Outbound-Only Worker Architecture & Colab ToS
- Colab instances connecting back via outbound WebSocket (`/api/ws/colab`) or polling HTTP (`/api/colab/tasks/pending`) do not require exposing inbound server ports or public tunnels into the Colab VM. In addition to simplifying setup, this avoids Colab ToS bans on hosting public web services/proxies from free-tier runtimes.

### 10. Constant-Time Secret Verification
- API token authentication in FastAPI handlers should use `secrets.compare_digest` rather than `!=` to eliminate timing side channels, and must check that both candidate and secret are non-empty strings.

## 2026-09-25: Local Torch Model Scaffold (Map #71)

### 11. Import-Guarded PyTorch & CUDA Detection
- Machines running backend unit tests or non-GPU nodes may not have `torch` or NVIDIA CUDA drivers installed.
- Any GPU memory queries (`torch.cuda.mem_get_info`, `torch.cuda.is_available`) or cache clearing (`torch.cuda.empty_cache`) must be enclosed in guarded `try ... except (ImportError, Exception)` blocks so the server boots cleanly and tests pass deterministically in headless CI / CPU environments without raising unhandled import errors.

### 12. Celery Queue Isolation for Mixed Hardware Workloads
- Celery workers with concurrency > 1 on CPU queues (`media.fast`, `media.heavy`) can starve or conflict with GPU-intensive diffusion/transformers workloads if routed to common queues.
- Creating an isolated `media.gpu` queue with dedicated task routes prevents CPU tasks (e.g. ffmpeg transcoding) from competing for worker slots with local VRAM-guarded inference tasks.

### 13. Honest Degraded Tier Contract
- When local ML execution cannot fit into GPU memory or when no GPU is detected, returning fake byte payloads ("Mock ... bytes") violates data integrity and corrupts downstream media decoders.
- Surfacing a typed degraded envelope (`degraded: true` with machine-readable `reason` such as `insufficient_vram` or `no_gpu`) enables the API client and UI to present transparent fallback options (e.g., auto-downgrading from Flux to SDXL, routing to cloud APIs, or displaying actionable VRAM requirements) rather than masking failure with corrupted files.

### 14. Registry Lookup Must Precede Hardware Detection
- Resolving a resource *after* probing hardware misclassifies `model_not_found` as `no_gpu` on GPU-less CI hosts, so tests pass for the wrong reason and production reports a misleading reason code.
- Order operations as: validate the request (is the model registered?) -> probe the environment (is there a GPU?) -> check capacity (does it fit?). Unknown-input errors must be independent of host capability.

### 15. Lazy-Loaded Expensive Resources Need a Lock
- A check-then-load sequence without synchronization is a double-allocation race: two workers both observe "not loaded" and both allocate a 13 GB model on a 16 GB GPU.
- Hold a reentrant lock across the whole check+load+cache transition (RLock so nested helpers like `unload_model` from `register` stay safe). Accept that this serializes loads of *different* models too - on a GPU that is desirable, not a bottleneck.

### 16. Monkeypatching the Wrong Seam Produces Pass-By-Luck Tests
- A test patching `app.tasks.vram_guard` against a function that does `from app.ml.guard import vram_guard` *inside its body* patches a name nobody reads; it only passes because the real guard raises on a GPU-less machine.
- Always patch where the name is **read**, not where it is thought to live, and assert the mock was actually invoked. Similarly, a function-local `import torch` can only be intercepted via `sys.modules`, never via `setattr(module, "torch", ...)`.
- Red-flag heuristic: a test that asserts a property of a string it constructed itself proves nothing.

### 17. E2E Output Filename Regex Rigidity
- `frontend/e2e/05-generation-catalog.spec.ts` strictly validates generated filenames with `^gen_image_\d+\.png$`.
- Appending alphanumeric uuid fragments (e.g. `gen_image_1700000000_a1b2c3.png`) breaks downstream E2E regex contracts - keep the suffix pure digits. Seconds (`int(time.time())`) collide when two requests finish in the same second, so use `time.time_ns()`: still all digits, effectively collision-free.

### 18. Local Inference Diffusers Lazy Import Boundary
- In environments without CUDA or PyTorch/diffusers dependencies, top-level diffusers imports will prevent the FastAPI application from booting.
- Encapsulate diffusers pipeline loading (`FluxPipeline`, `StableDiffusionXLPipeline`) inside lazy loader factory callbacks executed only when `model_registry.load_model` is triggered on an admitted GPU job.

### 19. GPU-Only Bugs Hide From CPU Test Suites
- Two #100 defects were invisible to a 245-test green suite and only surfaced in review: `pipe.to("cuda")` loading ~34 GB of FLUX bfloat16 (instant OOM on the 16 GB floor), and `680`-pixel edges (not divisible by 16, fatal to FLUX's 2x2 latent patchification).
- Neither raises on a machine without torch. Anything whose correctness depends on hardware geometry - VRAM totals, tensor shape divisibility, dtype size - needs a *numeric assertion in a plain unit test* (`edge % 16 == 0`, `roster_vram <= floor`), not an end-to-end run.
- Rule of thumb: if the only way to fail is to execute the model, you do not have a test.

### 20. Don't Accept a Parameter You Cannot Honor
- `denoising_strength` was accepted on a text-to-image route with no source image. Diffusers raises `TypeError` on `strength` for txt2img; the try/except then reported it as `load_failed`, i.e. a bogus infrastructure error for a client input problem.
- Two failure modes to avoid: forwarding it (crashes into an unrelated error bucket) and silently dropping it (the response echoes a parameter that did nothing). Reject with 400 and an actionable message until the feature that needs it exists.

### 21. Parameter Shadowing with Builtin Python Names
- Using `type: str = "tts"` as a function argument shadows Python's builtin `type()`, causing runtime errors when attempting `type(obj)` in exception messages or type inspect calls.
- In handlers with legacy `type` query params, use `obj.__class__.__name__` or assign `audio_type = type` immediately to prevent type-check confusion and namespace collisions.

### 22. Voice Clone Markers Contract Without Schema Migration
- Providing waveform player markers (`time: 0.0, label: "voice clone: ...", kind: "voice_clone"`) in the API response allows the frontend waveform player to render clone start positions immediately upon generation.
- To persist marker provenance across catalog reloads without requiring an Alembic schema migration on `MediaAsset`, prefixing the asset title with `Voice Clone: <prompt[:30]>...` allows the frontend UI to deterministically reconstruct the clone marker on playback.

### 23. Zero-Copy WAV Header Introspection for Duration
- Parsing audio duration directly from in-memory WAV byte arrays using Python's standard library `wave.open(io.BytesIO(wav_bytes), "rb")` yields exact duration (`frames / framerate`) without invoking heavy external dependencies like `ffmpeg` or `sox`.
- If the byte stream is malformed or non-WAV, cleanly falling back to the requested duration parameter or a sensible default prevents upload failures.

### 24. Resident Model Eviction and Inference Serialization
- When loading multi-gigabyte models (e.g. FLUX.1 schnell ~13GB and MusicGen large ~10.4GB) on a 16GB GPU, resident models must be evicted when switching pipelines (`evict_except(keep_ids)`) to prevent `insufficient_vram` deadlocks.
- Admission, model load, and inference must be serialized behind a global `INFERENCE_LOCK = threading.RLock()` across both image and audio pipelines to ensure eviction never runs while another request is mid-inference.
- Audio references for zero-shot voice cloning must be resolved from S3/MinIO storage into secure temporary files (`tempfile.NamedTemporaryFile`) and passed as `speaker_wav` to XTTS with guaranteed cleanup.

### 25. SVD Video Pipeline Progress Mapping & FFmpeg Carriage Return Scrapes
- Stable Video Diffusion (SVD) generation involves two distinct stages: neural latent denoising (diffusers steps) and MP4 video encoding (ffmpeg binary).
- To present smooth monotonic progress in the UI (which monitors `status.info.percent` between 0 and 99), denoising steps map to 0-79% and ffmpeg frame encoding maps to 80-99% (strictly capped at 99 so the Celery task remains in PROGRESS state until final return).
- FFmpeg progress updates on stderr use carriage return (`\r`) rather than newline (`\n`), requiring character-by-character chunked reads or splitting on `\r` and `\n` to reliably scrape `frame=\s*(\d+)` progress lines without buffering stalls.

### 26. CPU vs. GPU PyTorch Dtype Selection & Subprocess Lifecycle Protection
- Stable Video Diffusion (SVD) and similar diffusion pipelines must not use `torch.float16` unconditionally: on CPU (`cuda == False`), PyTorch float16 convolution and attention kernels raise fatal runtime errors. Explicitly selecting `torch.float16 if cuda else torch.float32` preserves the GPU VRAM contract while keeping CPU fallback safe.
- Subprocesses invoked during inference (such as `ffmpeg` for MP4 encoding) must be guarded with `try/finally` blocks that actively kill the child process (`process.kill()`) and close stream handles (`process.stderr.close()`) if exceptions occur or if `progress_cb` fails; otherwise stalled children orphan and leave locks like `INFERENCE_LOCK` held indefinitely.
- Background worker tasks (Celery) executing generative jobs must guarantee terminal database updates (`Task.status = "FAILED"`) and Redis pub/sub notifications on both unhandled exceptions and degraded responses (`degraded: true`), preventing tasks from lingering in `PROCESSING` state indefinitely.

### 27. Polling State Machines Must Record Results Before Branching on Them
- A poller that early-returns on a degraded/failed payload *before* storing that payload leaves the render branch below it unreachable: the styled error card becomes dead code and the panel silently falls back to its idle/empty state while the API correctly returned 200. Store the payload first, then branch on its fields.
- Task-status pollers need a wall-clock deadline, not just terminal-state checks — if the worker process dies between dispatch and completion, `PROGRESS` simply stops arriving and a `setInterval` without a deadline polls `/api/tasks/status` forever while showing a stale progress bar.
- Celery `FAILURE` payloads are not guaranteed to be strings (`info` may be a dict/exception repr); string interpolating them renders `[object Object]`. Normalise through a single `formatTaskFailure()` helper so user-facing error text stays legible.
- Handing a generated asset to a player must carry its physical parameters (here `fps`): a player that defaults to 30 fps steps frames at the wrong interval and reports the wrong frame index for a 7 fps clip.







