# FusionClip

FusionClip is an open-source, self-hosted multimedia management and generation dashboard designed to coordinate video, audio, and image handling using commercial APIs, local inference models, and remote Google Colab GPU compute nodes.

## Getting Started

See the **[User Guide](USER_GUIDE.md)** for complete instructions on running FusionClip with Docker Compose or local development, including prerequisites, configuration, and troubleshooting.

### Quick Start (Docker Compose)

```bash
git clone https://github.com/parth5012/FusionClip.git
cd FusionClip
docker compose up -d
```

Then open **http://localhost:3000** in your browser.

## Core Stack
- **Frontend**: Next.js (React, TypeScript, Tailwind CSS)
- **Backend API**: FastAPI (Python)
- **Database**: PostgreSQL with `pgvector` for semantic multimedia search
- **Task Queue**: Redis + Celery (with eventlet/solo support for Windows)
- **Object Storage**: MinIO (S3-compatible local cache)

## Key Features
1. **Unified Multimedia Library**: Manage uploads, exports, and metadata tags with custom video/audio waveform player integrations.
2. **Local Generative Models**: Generate images (Flux.1 / SDXL), audio/sound effects (XTTS v2 / ChatTTS / MusicGen), and short videos (Stable Video Diffusion).
3. **Google Colab Connector**: Expose an ephemeral cloud GPU server using Cloudflare Tunnels or ngrok, allowing cheap/free high-power remote processing.
4. **Magnific-Style Generative AI Upscaler**: Enhance low-resolution images with high-frequency details using ControlNet Tile + SDXL/Flux tile blending.
5. **Background task monitoring & logs**: Track task completion percentages, VRAM/GPU resources, and failure trace captures.

## Planning & Wayfinding
Project blueprints and architectural choices are managed as local markdown wayfinding tickets:
- The [Wayfinding Map](.scratch/fusionclip/map.md) acts as the index for decided vs under-discussion issues.
- Detailed implementation decisions lie under the [issues folder](.scratch/fusionclip/issues/).

## License
Licensed under the [MIT License](LICENSE).
