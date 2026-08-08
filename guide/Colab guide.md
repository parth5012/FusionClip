# Google Colab Compute Connector — User Guide

## Overview

The Google Colab Compute Connector bridges the FusionClip multimedia platform with Google Colab GPU notebooks. It lets you offload heavy generative workloads (image generation, audio synthesis, text generation) from your local machine to free/cheap Colab GPU runtimes, with results automatically saved back to your FusionClip gallery.

## Architecture

```
┌─────────────────┐     WebSocket/HTTP      ┌──────────────────┐
│   FusionClip    │ ◄──────────────────────► │  Google Colab    │
│   Backend       │     Redis pub/sub        │  Notebook        │
│   (FastAPI)     │                          │  (colab_client)  │
└────────┬────────┘                          └────────┬─────────┘
         │                                            │
         │ REST + WebSocket                           │ GPUtil / psutil
         ▼                                            ▼
┌─────────────────┐                          ┌──────────────────┐
│   FusionClip    │                          │  T4 GPU Runtime  │
│   Frontend      │                          │  (Model execution)│
│   (Next.js)     │                          └──────────────────┘
└─────────────────┘
```

## Components

### 1. `colab_client.py` — Colab Notebook Client

**Location:** `colab_client.py` (run this inside your Colab notebook)

**What it does:**
- Connects to the FusionClip backend via WebSocket (`/api/ws/colab`)
- Authenticates using your `FUSIONCLIP_SECRET_KEY`
- Reports system metrics (VRAM, RAM, CPU) every few seconds
- Listens for incoming task dispatches via Redis pub/sub
- Sends progress updates and final results back
- Auto-reconnects with exponential backoff if the tunnel drops

**How to use:**
1. Open a new Google Colab notebook
2. Select **Runtime → Change runtime type → T4 GPU**
3. Paste the contents of `colab_client.py` into a cell
4. Run the cell — the client connects automatically

---

### 2. WebSocket/HTTP Bridge — Backend Communication Layer

**Location:** `backend/app/routers/settings.py`

**Endpoints:**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `WS` | `/api/ws/colab` | Primary channel — Colab connects here, receives tasks, sends metrics/results |
| `GET` | `/api/colab/tasks/pending` | HTTP fallback — Colab polls for tasks if WebSocket drops |
| `POST` | `/api/colab/tasks/update` | HTTP fallback — Colab reports progress/results |
| `POST` | `/api/colab/metrics` | HTTP fallback — Colab pushes system metrics |
| `GET` | `/api/colab/metrics` | Frontend polls this to get latest metrics |

**Authentication:** All endpoints require the `token` query parameter matching `FUSIONCLIP_SECRET_KEY`.

---

### 3. Automated Colab Dispatch — Task Routing

**Location:** `backend/app/routers/generate.py`, `backend/app/tasks.py`

**How it works:**
1. When you generate content, the system checks `is_colab_connected()` (reads `colab:connected` from Redis)
2. If Colab is online, the task is dispatched to Colab instead of running locally
3. If Colab is offline, the original mock/local behavior is used as fallback

**Task types dispatched to Colab:**

| Task Type | Trigger | Payload |
|-----------|---------|---------|
| `text_generation` | POST `/api/generate/text` | `{ prompt }` |
| `audio_generation` | POST `/api/generate/audio` | `{ prompt, type }` |
| `image_generation` | POST `/api/generate/image` | `{ prompt, steps, scale }` |

**Dispatch flow:**
1. User clicks generate in the FusionClip UI
2. Backend publishes task to Redis `colab_dispatches` channel
3. Colab notebook receives it via WebSocket
4. Colab sends progress updates (`task_progress`) during execution
5. On completion, Colab sends `task_complete` with the output URL
6. Backend saves the result as a `MediaAsset` in the database
7. User sees the generated asset in their gallery

---

### 4. Compute Monitor — Frontend Dashboard

**Location:** `frontend/src/components/MonitorPanel.tsx`

**Features:**
- **Live gauges** — VRAM, RAM, CPU with color-coded progress bars
- **Sparkline charts** — Rolling history of the last ~4 minutes (120 samples)
- **Connection status** — Connected/Disconnected indicator with live dot
- **Active task** — Shows what Colab is currently working on
- **Polling interval** — Polls `GET /api/colab/metrics` every 2 seconds

**How to access:** Click "Compute Monitor" in the sidebar navigation.

---

## User Setup Guide

### Step 1: Configure the tunnel

Inside your Colab notebook, create a tunnel using ngrok or Cloudflare:

```python
# Example with ngrok
!pip install pyngrok
from pyngrok import ngrok
public_url = ngrok.connect(8080)
print(public_url)
```

### Step 2: Add tunnel URL to FusionClip

1. Open FusionClip in your browser
2. Go to **Configuration** (sidebar)
3. Paste the tunnel URL in "Cloudflare / ngrok Endpoint URL"
4. Click **Save Endpoint**
5. Toggle the tunnel status to **Running**

### Step 3: Start the Colab client

1. In your Colab notebook, paste the contents of `colab_client.py`
2. Run the cell
3. The client connects automatically — you'll see "Connected" in the notebook output

### Step 4: Generate content

1. Go to **Generative AI** in the sidebar
2. Create an image, audio, or text as you normally would
3. The task is automatically routed to Colab
4. Watch live progress in **Compute Monitor**

---

## API Reference

### WebSocket: `/api/ws/colab?token=<SECRET>`

**Client → Server messages (JSON):**

```json
// Metrics report
{
  "type": "metrics",
  "vram_used": 4096.0,
  "vram_total": 15360.0,
  "ram_used": 8192.0,
  "ram_total": 13945.0,
  "cpu_load": 45.2,
  "active_task": "image_generation"
}

// Task progress
{
  "type": "task_progress",
  "task_id": "colab_gen_image_abc12345",
  "percent": 50
}

// Task complete
{
  "type": "task_complete",
  "task_id": "colab_gen_image_abc12345",
  "output": {
    "url": "https://.../generated_image.png",
    "filename": "generated_image.png"
  }
}

// Task failed
{
  "type": "task_failed",
  "task_id": "colab_gen_image_abc12345",
  "error": "CUDA out of memory"
}
```

**Server → Client messages (JSON):**

```json
// Task dispatch
{
  "type": "task_dispatch",
  "task_id": "colab_gen_image_abc12345",
  "task_type": "image_generation",
  "parameters": {
    "prompt": "A sunset over mountains",
    "steps": 28,
    "scale": 7.5
  }
}
```

### HTTP: `GET /api/colab/metrics`

**Response (connected):**
```json
{
  "status": "connected",
  "metrics": {
    "vram_used": 4096.0,
    "vram_total": 15360.0,
    "ram_used": 8192.0,
    "ram_total": 13945.0,
    "cpu_load": 45.2,
    "active_task": "image_generation",
    "vram_percent": 26.7,
    "ram_percent": 58.7,
    "updated_at": 1723100000.0
  }
}
```

**Response (disconnected):**
```json
{
  "status": "disconnected",
  "metrics": null
}
```

### HTTP: `POST /api/colab/tasks/update?token=<SECRET>`

**Request body:**
```json
{
  "task_id": "colab_gen_image_abc12345",
  "status": "COMPLETED",
  "progress": 100,
  "output": {
    "url": "https://.../image.png",
    "filename": "image.png"
  }
}
```

---

## Fallback Behavior

| Scenario | Behavior |
|----------|----------|
| Colab connected | Tasks dispatched to Colab via WebSocket |
| Colab disconnected | Tasks fall back to original mock/local responses |
| WebSocket tunnel drops | Colab uses HTTP polling fallback (`GET /api/colab/tasks/pending`) |
| Colab execution times out (60s) | Task marked FAILED, error returned to user |
| Colab reports error | Task marked FAILED with error message |

---

## File Map

| File | Purpose |
|------|---------|
| `colab_client.py` | Standalone client script for Colab notebooks |
| `backend/app/routers/settings.py` | WebSocket endpoint, HTTP fallbacks, metrics endpoints |
| `backend/app/routers/generate.py` | `is_colab_connected()`, `dispatch_gen_to_colab()`, modified generate endpoints |
| `backend/app/tasks.py` | Colab offloading in `process_media_heavy` Celery task |
| `frontend/src/components/MonitorPanel.tsx` | Live gauges, sparkline charts, connection status |
| `frontend/src/components/Sidebar.tsx` | "Compute Monitor" navigation item |
| `frontend/src/store/useStore.ts` | `colabMetrics` state and history management |
| `frontend/src/utils/api.ts` | `fetchColabMetrics()` API utility |
| `backend/tests/test_routers_smoke.py` | Test suite (177 tests) covering auth, WebSocket, HTTP fallbacks, metrics, Colab routing |

---

## Status: What's Real vs What's Mock

| Component | Status |
|-----------|--------|
| WebSocket bridge | ✅ Real — works with live Colab |
| HTTP fallbacks | ✅ Real |
| Metrics reporting | ✅ Real — Colab reports actual GPUtil/psutil data |
| Task dispatch to Colab | ✅ Real — Colab receives task payloads |
| Result handling & MediaAsset saving | ✅ Real |
| Frontend fallback when disconnected | ✅ Real — falls back to mock responses |
| **Actual model execution on Colab** | ⚠️ User implements model inference in their notebook |

> **Note:** The communication and orchestration layer is fully built and tested. The actual model inference code (running Flux, ElevenLabs, Gemini inside Colab) is the user's responsibility to implement in their notebook. The `colab_client.py` receives task payloads — what it does with them depends on what models the user has set up in their Colab environment.
