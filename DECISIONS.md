# Architectural Decision Records

## 2026-10-14: MediaDerivativeService Contract & Invariants (Map #151, Issue #152)

### Context
Generative pipelines across FusionClip (`/api/upscale`, `/api/skin-enhance`, `/api/bgremove`, `/api/editor`) duplicate logic for object storage uploads, stem sanitization, catalog recording, and failure rollback. Ticket #152 resolved the unified interface and transaction invariants for `MediaDerivativeService`.

### Decisions
1. **Standardized Derivative Object Key Structure**:
   - Format: `{pipeline_folder}/{clean_stem}_{qualifier}_{token}.{ext}` (or `{pipeline_folder}/{clean_stem}_{token}.{ext}` if qualifier is empty).
   - Pipeline folders: `upscaled`, `skin_enhanced`, `bg_removed`, `edited`.
   - Stems sanitized using alphanumeric characters and hyphens/underscores `[A-Za-z0-9._-]` stripped of leading/trailing `._`, falling back to `asset` if empty.
   - 12-hex collision-free token (`uuid.uuid4().hex[:12]`) ensures concurrent requests on identical sources never collide.
   - *Alternatives considered*: Pure random UUID tokens (rejected: loses human-readable source context in storage inspector), caller format patterns (rejected: encourages cross-pipeline drift).

2. **Synchronous Compensating Deletes on Database Failure**:
   - When database operations or `db.commit()` fail, `MediaDerivativeService` calls `db.rollback()` and immediately executes synchronous compensating deletes (`delete_object(key)`) for all uploaded objects and auxiliary sidecars.
   - Deletions are individually guarded in `try...except` blocks logging warnings, ensuring cleanup errors never mask or swallow the original database exception.
   - *Alternatives considered*: Celery background queue (rejected: introduces broker dependency and orphan leaks when worker is offline), deferred scavenger (rejected: leaks storage until an unbuilt scavenger runs).

3. **Relational Lineage via `MediaAsset.source_path`**:
   - Lineage pairing is established via `MediaAsset.source_path` referencing the parent asset's `file_path`.
   - Existing `BeforeAfterModal` and `GET /api/media` (which dynamically signs `source_url`) work out of the box with zero schema migrations required.
   - *Alternatives considered*: New JSON column on `MediaAsset` (rejected: requires Alembic migration for information already present or stored in `Task.logs`), tag-based metadata (rejected: overcomplicates before/after pairing queries).
