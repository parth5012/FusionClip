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



