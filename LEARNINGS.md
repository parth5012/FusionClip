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



## 2026-09-24: Magnific upscaler ship (#96)

- **`task_id[:6]` is not unique enough**: two `upscale_*` ids sharing the first 6 chars cross-linked `file_path.contains(prefix)` status lookups → silent wrong-job results. Fix: per-job `uuid4().hex[:12]` token embedded in the output object path; status lookup contains the token (not the id prefix).
- **Hand-rolled "minimal PNG" bytes can be structurally valid (signature/IHDR/IEND) yet have a corrupt IDAT stream**: FastAPI upload round-trips bytes fine, but PIL `Image.open().convert('RGB')` raises `OSError: broken data stream when reading image file` only when the pipeline decodes. E2E fixture must be PIL-verified, not just byte-plausible. A 1×1 PNG with IDAT `78 9c 63 f8 cf c0 00 00 03 01 01 00 c9 fe 92 ef` (zlib deflate of `\x00\xff\x00\x00\x00`) decodes cleanly.
- **Playwright `<option>` elements inside a closed `<select>` are never "visible"**: `expect(option).toBeVisible()` always fails even when the option is present. Assert `toHaveCount(1)` (or rely on `selectOption`'s built-in wait) instead.
- **E2E tests that seed state via an earlier test are order-coupled**: making the panel test self-seed its own upload via `apiUploadFile` removes the dependency on test 2's UI upload having completed.
- **No-Docker local e2e stack recipe**: moto server on :9000 + uvicorn :8001 (SQLITE DATABASE_URL, MINIO_ENDPOINT=127.0.0.1:9000, CORS_ORIGINS for the next dev origin) + `next dev` on :3001 with `NEXT_PUBLIC_API_URL` pointing at the backend. Ports 8000/3000 may be held by a sibling worktree — pick alternates.
- **Playwright browser revision mismatch workaround**: when `npx playwright install` can't fetch (CDN redirect 400), symlink the expected revision dir (`chromium-1234 -> chromium-1243`) in `~/.cache/ms-playwright/`; binary layout matches on linux-x64.
