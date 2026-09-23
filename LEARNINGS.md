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
