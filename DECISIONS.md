# Architectural Decision Records

## 2026-10-14: MediaDerivativeService Contract & Invariants (Map #151, Issue #152)

### Context
Generative pipelines across FusionClip (`/api/upscale`, `/api/skin-enhance`, `/api/bgremove`, `/api/editor`) duplicate logic for object storage uploads, stem sanitization, catalog recording, and failure rollback. Ticket #152 resolved the unified interface and transaction invariants for `MediaDerivativeService`.

### Decisions
1. **Standardized Derivative Object Key Structure**:
   - Format: `{pipeline_folder}/{clean_stem}_{qualifier}_{token}.{ext}` (or `{pipeline_folder}/{clean_stem}_{token}.{ext}` if qualifier is empty).
   - Pipeline folders: `upscaled`, `skin_enhanced`, `bg_removed`, `edited`.
   - Stems sanitized using alphanumeric characters and hyphens/underscores `[A-Za-z0-9._-]` stripped of leading/trailing `._`, falling back to `asset` if empty.
   - 12-hex unique token (`uuid.uuid4().hex[:12]`) provides collision resistance across concurrent runs on identical sources. Custom tokens are sanitized and validated.
   - Guard against self-overwrite: `output_path` is explicitly verified to never equal `source_path`.
   - Keys strictly validated against control characters (`\x00`..`\x1f`, `\x7f`), path traversals (`..`), and double slashes (`//`).
   - *Alternatives considered*: Pure random UUID tokens (rejected: loses human-readable source context in storage inspector), caller format patterns (rejected: encourages cross-pipeline drift).

2. **Compensating Deletes & Deferred Commit Protocol**:
   - For `auto_commit=True`, when database operations or `db.commit()` fail, `MediaDerivativeService` calls `db.rollback()` and immediately executes synchronous compensating deletes (`delete_object(key)`) for all uploaded objects and auxiliary sidecars.
   - For `auto_commit=False`, the caller manages transaction boundaries. `MediaDerivativeService` flushes the row to assign `asset.id`. On flush or upload error, compensating deletes execute and the exception is re-raised without rolling back the caller's session.
   - On deferred caller commit failure, callers invoke `deriv_res.cleanup()` (exposed via `DerivativeResult.uploaded_keys`) to cleanly remove all uploaded derivative objects and sidecars.
   - Deletions are individually guarded in `try...except` blocks logging errors if `delete_object` returns `False` or raises, ensuring cleanup errors never mask or swallow the original database exception.
   - *Alternatives considered*: Celery background queue (rejected: introduces broker dependency and orphan leaks when worker is offline), deferred scavenger (rejected: leaks storage until an unbuilt scavenger runs).

3. **Relational Lineage via `MediaAsset.source_path`**:
   - Lineage pairing is established via `MediaAsset.source_path` referencing the parent asset's `file_path`.
   - Existing `BeforeAfterModal` and `GET /api/media` (which dynamically signs `source_url`) work out of the box with zero schema migrations required.
   - *Alternatives considered*: New JSON column on `MediaAsset` (rejected: requires Alembic migration for information already present or stored in `Task.logs`), tag-based metadata (rejected: overcomplicates before/after pairing queries).

## 2026-10-15: Distributed Inference Execution Seam & VRAM Admission Semantics (Map #155, Issue #156)

### Context
FastAPI Uvicorn workers and Celery prefork child processes run across OS process boundaries. Previously, `INFERENCE_LOCK = threading.RLock()` in `backend/app/ml/registry.py` only serialized threads within a single Python process, risking simultaneous GPU execution, CUDA memory collisions, and OOM panics in multi-process deployments. Ticket #156 resolves the distributed concurrency model, cross-process eviction protocol, and crash recovery semantics.

### Decisions
1. **Exclusive Distributed Redis Mutex**:
   - Concurrency is strictly serialized across all API and Celery workers via an exclusive Redis mutex (`ml:lock:gpu:{device}`).
   - An in-memory non-blocking `RLock` adapter is provided for CI and local unit tests, preserving fast in-memory execution when Redis is unavailable (`one adapter = hypothetical seam, two adapters = real seam`).
   - *Alternatives considered*: Redis counting semaphore (rejected: high risk of CUDA OOM when bursty model allocations overlap).

2. **Cross-Process Eviction via Redis Pub/Sub Signal**:
   - When a worker acquiring the distributed lock detects insufficient free VRAM for model admission, it publishes an eviction broadcast on channel `ml:gpu:evict`.
   - Peer workers running listener threads receive the broadcast, evict idle resident models (`model_registry.unload_all()` or `evict_idle()`), and trigger `torch.cuda.empty_cache()`.
   - The acquiring worker pauses briefly and re-samples available VRAM before proceeding or raising `InsufficientVRAMError`.
   - *Alternatives considered*: Ephemeral loading / eager unloading on every request (rejected: severe latency degradation from constantly reloading multi-gigabyte model weights from disk).

3. **Lease TTL, Heartbeat Auto-Renew & Crash Deadlock Protection**:
   - Mutex lease TTL is set to 60 seconds with a background heartbeat thread auto-renewing the lock every 15 seconds while inference executes.
   - If a worker crashes or is terminated by the OS/OOM-killer mid-inference, the lease auto-expires within 60 seconds, preventing permanent deadlocks.
4. **Adversarial Review Invariants & Seam Refinement**:
   - `_atomic_extend` differentiates between confirmed ownership loss (token mismatch) and transient network/Redis errors. The heartbeat worker retries transient errors while the lease remains valid and only halts renewal if ownership is truly lost.
   - `is_owner()` provides an active verification check on the seam interface so workers can verify lock status before committing expensive VRAM allocations or output mutations.
   - Separate process-local state lock (`threading.RLock`) protects `ModelRegistry` dictionary mutations from cross-process contention during startup and queries (`has_loader`), while the distributed `_gpu_lock` strictly wraps actual weight allocations in `load_model`.
   - Backend selection is explicit via `INFERENCE_LOCK_BACKEND=redis|memory`. When `redis` is configured, connection failures fail fast with configured socket timeouts rather than silently falling back to a split-lock in-memory adapter.
   - Lock acquisition errors in Celery tasks are caught and translated into the Decision #3 degraded-response contract (`DegradedReason.NO_GPU`), preventing unexpected Celery task failures under lock contention or Redis drops.


