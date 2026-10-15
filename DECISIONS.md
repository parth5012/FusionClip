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
