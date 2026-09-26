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


## 2026-09-25: Merging divergent feature branches

- **Shared-closer JSX conflicts: count EVERY closer line, including conditionals.** When both sides of a conflict end in identical closers (`))}`, `</div>`, `</div>`, `)}`), mirroring them around each side requires all four lines. Dropping the trailing `)}` (the `{cond && (` close) leaves the conditional open and the parser reports a misleading `')' expected` at the *next* block, far from the actual omission.
- **Diff structural strategies must follow content shape, not just marker order**: for a "return (` JSX opening conflict, wrap `main's_opening_div + ours_panel + closers + main's_blocks + closers + shared_tail` — the opening tag comes from one side, the bodies alternate, and the closers are duplicated verbatim from the shared gap.
- **Cold-start Playwright flakes masquerade as regressions**: the first e2e run after booting the stack pays Next.js compilation + moto first-put latency, which can blow a 20s visibility timeout even though the server-side operation succeeds (backend log shows the 200). Re-run isolated *and* full-suite warm before diagnosing.
- **Local e2e without Redis**: the body-based `/api/upscale` flow dispatches via FastAPI `BackgroundTasks` (in-process, no broker), while `/api/tasks/*` dispatch goes through Celery `.delay()` and hard-fails without a broker. A no-Docker environment can verify the former fully; the latter needs the docker stack (no `redis-server` binary, no passwordless sudo).
- **Dead-code audit during merges**: main's `startUpscale(path, params)` and its unused `useStore` destructure in FileManager had zero callers — keeping them would have created a duplicate-identifier (`setUpscaleTarget` local state vs store destructure) that `tsc` would reject. Grep call sites for both sides' symbols before choosing to union them.


## 2026-09-26: Batch select + zip export with derivatives (#106)

- **SQLAlchemy `db.close()` in Celery tasks with shared test session**: When `patch_tasks_db` routes `SessionLocal` to a test `db_session`, calling `db.close()` inside the task body closes the test session and expunges attached ORM instances. Calling `db_session.refresh(model_instance)` in test assertions afterwards throws `InvalidRequestError: Instance is not persistent within this Session`. Test assertions must re-query `db_session.query(Task).filter(...)` rather than calling `refresh()` on the pre-task object.
- **Archive collision protection for multi-asset exports**: When bundling multiple assets and their derivatives into a flat or structured zip archive, identically-named files (or derivatives with common output names) collide if arcnames are not deduplicated. Tracking `used_arcnames` with indexed suffix fallbacks (`name_1.ext`, `name_2.ext`) prevents silent archive overwrites.
- **FastAPI 400 Bad Request vs Pydantic 422**: When an API contract mandates 400 for empty selection payloads (`asset_ids: []`), Pydantic's default `Field(..., min_length=1)` raises 422 Unprocessable Entity. Defaulting `asset_ids: List[int] = Field(default_factory=list)` and explicitly raising `HTTPException(status_code=400, detail=...)` inside the endpoint handler enforces the required 400 contract without breaking request schema parsing.
- **In-Memory Zip DoS & Tempfile Streaming**: Buffering multi-asset zip archives in `io.BytesIO` scales memory linearly with payload size and risks OOM worker crashes. Using `tempfile.NamedTemporaryFile` writes zip bytes to disk incrementally and allows streaming directly to S3 via file handles (`s3.put_object(Body=fh)`), followed by deterministic cleanup in `finally:`.
- **Zip-Slip Directory Traversal Sanitization**: File paths stored in DB (or imported from external sources) may contain `..` or backslashes (`uploads/../../evil.sh`). Zip entry names must normalize backslashes, strip paths via `os.path.basename`, and reject `.`/`..`/empty names falling back to safe deterministic basenames (`asset_{id}.bin`).
- **Deduplicating Explicit Selections with Relational Derivatives**: When an export job queries derivatives (`source_path.in_(parent_paths)`), if a user selects both a parent asset and its derivative explicitly, the derivative will be included twice unless the child query filters `~MediaAsset.id.in_(selected_ids)`.

## 2026-09-26: Task Logs & Error Diagnostics (Map #72, #108)

- **Surrogate Character Sanitization in Python string encoding**: External error messages or runtime strings with unmatched surrogates (e.g. `\ud83d\ude00`) throw `UnicodeEncodeError` when encoded to standard UTF-8. Sanitizing via `s.encode('utf-8', errors='replace').decode('utf-8')` before JSON serialization and byte-length measurement ensures error capture never fails on malformed input.
- **Celery Signal Boundaries vs Direct Invocations**: Celery signals (`task_prerun`, `task_postrun`, `task_failure`, `task_retry`) automatically hook all worker-dispatched task executions, but internal failure helpers (`_handle_task_failure`) can be invoked directly in unit tests. Dual-instrumenting with consecutive-event deduplication ensures all execution paths are covered without duplicate events.
- **NDJSON Log Storage & Resilience**: Storing lifecycle events as JSON Lines (NDJSON) capped at a fixed number of events (50) and bytes (64KB) guarantees bounded DB rows. Line-by-line parsing with fallback wrapping ensures legacy unformatted text rows or corrupt lines render cleanly without crashing the UI.

