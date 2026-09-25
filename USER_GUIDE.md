# FusionClip User Guide

This guide walks you through running FusionClip on your machine using either Docker Compose (recommended) or local development tools.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start with Docker Compose](#quick-start-with-docker-compose)
- [Local Development Setup](#local-development-setup)
- [Configuration](#configuration)
- [Accessing the Application](#accessing-the-application)
- [Running Tests](#running-tests)
- [Stopping the Project](#stopping-the-project)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### For Docker Compose (Recommended)

| Tool | Version | Download |
|------|---------|----------|
| Docker Engine | 20.10+ | [docker.com](https://docs.docker.com/engine/install/) |
| Docker Compose | v2.0+ | Included with Docker Desktop |
| Git | Any | [git-scm.com](https://git-scm.com/downloads) |

Verify your installation:

```bash
docker --version
docker compose version
```

### For Local Development

| Tool | Version | Download |
|------|---------|----------|
| Node.js | 18.x+ | [nodejs.org](https://nodejs.org/) |
| npm | 9.x+ | Included with Node.js |
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| PostgreSQL | 16+ with pgvector | [postgresql.org](https://www.postgresql.org/download/) or [pgvector](https://github.com/pgvector/pgvector#installation) |
| Redis | 7.x+ | [redis.io](https://redis.io/download) |
| MinIO | Latest | [min.io](https://min.io/download) |

---

## Quick Start with Docker Compose

The fastest way to run FusionClip. This starts all services (database, cache, storage, API, worker, and frontend) in isolated containers.

### 1. Clone the Repository

```bash
git clone https://github.com/parth5012/FusionClip.git
cd FusionClip
```

### 2. (Optional) Configure Environment Variables

A `.env` file with sensible defaults is already included. To customize:

```bash
cp .env.example .env
```

Edit `.env` to change ports, credentials, or storage paths. See [Configuration](#configuration) for all available variables.

### 3. Launch All Services

```bash
docker compose up -d
```

This pulls images, builds containers, and starts everything in the background. On first run, expect 2–5 minutes for image downloads and builds.

### 4. Verify Services Are Running

```bash
docker compose ps
```

All containers should show `healthy` or `up` status.

### 5. Access the Application

Open your browser to **http://localhost:3000**

See [Accessing the Application](#accessing-the-application) for full service URLs.

---

## Local Development Setup

Use this approach if you want to modify code with hot-reload, debug with IDE tooling, or avoid Docker entirely.

### 1. Clone the Repository

```bash
git clone https://github.com/parth5012/FusionClip.git
cd FusionClip
```

### 2. Start Infrastructure Services

You need PostgreSQL (with pgvector), Redis, and MinIO running. The easiest way:

```bash
# Start only the infrastructure containers
docker compose up -d db redis minio
```

Or install and run them natively on your system.

### 3. Set Up the Backend

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> **Upgrading an existing install**: if the database was created before
> migrations were introduced (i.e. `init_db()` ran `create_all` and there is
> no `alembic_version` table), `alembic upgrade head` will fail because the
> tables already exist. Either stamp the schema first and then upgrade, or
> apply the pending column by hand:
>
> ```bash
> # Option A — stamp the init migration, then apply the new one
> alembic stamp 95c3d48285e2
> alembic upgrade head
>
> # Option B — apply the pending change directly (adds the
> # source_path column used by the before/after comparison UI)
> psql $DATABASE_URL -c "ALTER TABLE media_assets ADD COLUMN IF NOT EXISTS source_path VARCHAR;"
> psql $DATABASE_URL -c "CREATE INDEX IF NOT EXISTS ix_media_assets_source_path ON media_assets (source_path);"
> ```

The API is now available at **http://localhost:8000**.

### 4. Start the Celery Worker

Open a new terminal:

```bash
cd backend
source venv/bin/activate   # or venv\Scripts\activate on Windows
celery -A app.celery_app.celery worker --loglevel=info -P threads
```

### 5. Set Up the Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start the development server
npm run dev
```

The frontend is now available at **http://localhost:3000**.

---

## Configuration

### Environment Variables

All configuration is managed through environment variables. The `.env` file in the project root is loaded automatically by Docker Compose.

#### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_ENV` | `development` | Runtime environment |
| `PORT` | `3000` | Frontend port |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend API URL (used by browser) |
| `BACKEND_PORT` | `8000` | Backend API port |
| `DATABASE_URL` | `postgresql://fusionclip:fusionclip123@db:5432/fusionclip` | PostgreSQL connection string |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |

#### MinIO / Object Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIO_ROOT_USER` | `fusionclip_admin` | MinIO admin username |
| `MINIO_ROOT_PASSWORD` | `fusionclip_password123` | MinIO admin password |
| `MINIO_ENDPOINT` | `minio:9000` | Internal service endpoint |
| `MINIO_CONSOLE_PORT` | `9001` | Web console port |
| `MINIO_BUCKET_NAME` | `fusionclip-media` | Default storage bucket |
| `MINIO_USE_SSL` | `false` | Enable SSL/TLS |
| `MINIO_EXTERNAL_ENDPOINT` | `http://localhost:9000` | Browser-accessible URL |

#### GPU Configuration (Optional)

| Variable | Description |
|----------|-------------|
| `NVIDIA_VISIBLE_DEVICES` | Set to `all` to expose GPUs to the worker container |

To enable GPU support in Docker Compose, uncomment the `deploy` block in the `worker` service:

```yaml
worker:
  # ... existing config ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
```

Requires the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

### Runtime Configuration (In-UI)

Some settings are configured through the application UI at runtime:

- **API Keys**: Google Gemini and ElevenLabs keys are entered in the Settings panel
- **Colab Tunnel**: Cloudflare or ngrok tunnel URL for remote GPU compute

These are stored in the browser's localStorage and the backend database.

---

## Accessing the Application

After starting the services, access these URLs:

| Service | URL | Description |
|---------|-----|-------------|
| **Frontend Dashboard** | http://localhost:3000 | Main web interface |
| **Backend API** | http://localhost:8000 | FastAPI REST API |
| **API Docs (Swagger)** | http://localhost:8000/docs | Interactive API documentation |
| **API Docs (ReDoc)** | http://localhost:8000/redoc | Alternative API documentation |
| **MinIO Console** | http://localhost:9001 | Object storage management UI |

### Default Credentials

| Service | Username | Password |
|---------|----------|----------|
| MinIO Console | `fusionclip_admin` | `fusionclip_password123` |
| PostgreSQL | `fusionclip` | `fusionclip123` |

> **Security Note**: Change default credentials before deploying to any network. Update the `.env` file and restart containers.

---

## Running Tests

### End-to-End Tests (Playwright)

E2E tests run against the full Docker Compose stack. Ensure all services are running first:

```bash
cd frontend

# Install Playwright browsers (first time only)
npx playwright install

# Run all tests (headless)
npm run test:e2e

# Run tests with browser visible
npm run test:e2e:headed

# Run tests with Playwright UI for debugging
npm run test:e2e:ui
```

### Backend Tests

```bash
cd backend
python -m pytest
```

---

## Stopping the Project

### Docker Compose

```bash
# Stop all containers (preserves data)
docker compose down

# Stop and remove all data volumes (clean slate)
docker compose down -v
```

### Local Development

Stop each terminal process with `Ctrl+C` in this order:
1. Frontend (`npm run dev`)
2. Celery worker
3. Backend (`uvicorn`)

If running infrastructure via Docker:

```bash
docker compose stop db redis minio
```

---

## Troubleshooting

### Container Won't Start

**Symptom**: `docker compose up` fails or containers exit immediately.

**Solutions**:
- Check port conflicts: ensure ports 3000, 5432, 6379, 8000, 9000, and 9001 are free
- View logs: `docker compose logs <service-name>` (e.g., `docker compose logs backend`)
- Rebuild containers: `docker compose up -d --build --force-recreate`

### Database Connection Errors

**Symptom**: Backend logs show `could not connect to server` or `Connection refused`.

**Solutions**:
- Wait for the database healthcheck to pass: `docker compose ps db`
- Verify `DATABASE_URL` matches your `.env` configuration
- For local dev, ensure PostgreSQL is running and pgvector is installed

### Frontend Can't Reach Backend

**Symptom**: Browser shows network errors or blank pages.

**Solutions**:
- Confirm `NEXT_PUBLIC_API_URL` in `.env` points to the backend (default: `http://localhost:8000`)
- Check backend is running: `curl http://localhost:8000/`
- Verify CORS settings in `backend/app/main.py`

### MinIO Bucket Not Created

**Symptom**: Upload failures or storage errors.

**Solutions**:
- Access MinIO Console at http://localhost:9001
- Log in with default credentials
- Create the `fusionclip-media` bucket manually if it doesn't exist

### Celery Worker Not Processing Tasks

**Symptom**: Tasks stay in "pending" state.

**Solutions**:
- Check worker logs: `docker compose logs worker`
- Verify Redis is running: `docker compose ps redis`
- Ensure the worker container has the same environment variables as the backend

### Windows-Specific Issues

- Use `docker compose` (not `docker-compose`) on Docker Desktop
- For local development, use `-P threads` pool for Celery (already set in docker-compose)
- If using WSL2, clone the repo inside the WSL filesystem for better performance

---

## Next Steps

- Explore the [Features Blueprint](features.md) for a detailed overview of all capabilities
- Configure API keys in the Settings panel for Gemini and ElevenLabs integrations
- Set up a Google Colab tunnel for remote GPU compute
- Review the [API documentation](http://localhost:8000/docs) for integration endpoints
