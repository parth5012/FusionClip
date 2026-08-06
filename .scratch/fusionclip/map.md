# Map: FusionClip

## Destination
An open-source multimedia management and generation platform (FusionClip) supporting audio, photo, and video generation/management using both API-based models (Gemini, ElevenLabs) and local/Colab-hosted models.

## Notes
- Issue tracker: Local Markdown under `.scratch/fusionclip/issues/`
- Domain: AI agent generation pipelines, media hosting/management, local/remote model orchestration (Google Colab, local servers).

## Decisions so far
- [01-framework-choice](issues/01-framework-choice.md) — Recommended stack: Next.js (React/TypeScript) for frontend, FastAPI (Python) for backend, PostgreSQL + pgvector, MinIO, and Redis + Celery.
- [02-features-definition](issues/02-features-definition.md) — Features defined in features.md, covering core management dashboard, API assets, local generative pipelines, Colab remote connector, and Magnific upscaling.
- [03-magnific-exploration](issues/03-magnific-exploration.md) — Magnific works via pre-upscaling, tile partitioning, ControlNet Tile + Img2Img, guided prompts, and tiled blending.
- [04-local-llms-generation](issues/04-local-llms-generation.md) — Local generations run on PyTorch/transformers/diffusers/XTTS v2/MusicGen exposed through FastAPI endpoints.
- [05-colab-integration](issues/05-colab-integration.md) — Expose remote Colab GPU python FastAPI server using cloudflared/ngrok tunnels, configured via settings in web app client.
- [06-windows-task-queuing](issues/06-windows-task-queuing.md) — For Windows-native task queues, use `celery --pool=solo` or `--pool=eventlet` configurations, or native thread-based alternatives like Huey.
- [07-user-setup-workflow](issues/07-user-setup-workflow.md) — Detail user journey for setup: Launch Colab notebook, execute packages, copy-paste tunnel endpoint URL to the app settings, connection verification, and image generation processing.

## Not yet specified
- Fine-grained job queue architecture for video/audio conversion and export (e.g., FFmpeg task worker).
- Database strategy for storing media metadata and model configurations (e.g., PostgreSQL + Vector DB for semantic searching).
- Cloud storage integration patterns (S3/MinIO) vs. local storage limits.

## Out of scope
- Native mobile applications (iOS/Android) - focus remains on web application at launch.
- Commercial multi-tenant subscription billing systems (Stripe) - build open-source self-hosted first.
