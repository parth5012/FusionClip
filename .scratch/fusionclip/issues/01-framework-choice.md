Status: resolved
Type: research
Blocked by: None

## Question
What framework stack should we use to build an open-source multimedia management and generation platform (FusionClip)? We need to support video, audio, and image handling, API-based generations, and local/remote model executions.

## Answer
To support both AI model coordination (which is Python-centric) and a rich, interactive web UI (which is JavaScript/TS-centric), the recommended stack for FusionClip is:

1. **Frontend**: Next.js (React, TypeScript, Tailwind CSS)
   - **Why**: Excellent support for handling multi-media files, server-side rendering for quick asset loads, component patterns, and easy integration with custom media player libraries (e.g., Video.js, WaveSurfer.js). Next.js API routes can act as a lightweight middleman.
2. **Backend**: FastAPI (Python)
   - **Why**: Python is the absolute standard for AI/ML libraries (PyTorch, Diffusers, Transformers). FastAPI is high-performance, supports async operations, automatically generates OpenAPI docs, and easily handles streaming assets/files.
3. **Database**: PostgreSQL (with pgvector extension)
   - **Why**: To store file metadata, generations audit logs, user settings, and enable vector embeddings search for searching multimedia (e.g., finding images by natural language descriptions).
4. **Queue/Task Engine**: Redis + Celery (Python) or BullMQ (Node/TypeScript)
   - **Why**: Image/video/audio generation takes time (from 2 seconds to several minutes). We need an asynchronous job worker to execute these generations out-of-band and update the frontend via WebSockets or polling.
5. **Storage**: MinIO (Self-hosted S3 alternative)
   - **Why**: Highly performance local object store. Easy to setup via Docker, and fully compatible with AWS S3, Cloudflare R2, or Google Cloud Storage when migrating to the cloud.

This separation of concerns (Next.js frontend + FastAPI backend + Celery worker) is the clean, industrial standard for modern generative AI applications.
