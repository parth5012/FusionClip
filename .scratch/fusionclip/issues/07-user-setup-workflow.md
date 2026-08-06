Status: resolved
Type: research
Blocked by: None

## Question
How does the workflow operate for an end-user configuring the platform, starting the remote Google Colab runner, and generating media assets?

## Answer
The end-user configuration and generation workflow is designed to be frictionless, hiding Python installation complexities behind Google Colab or straightforward local toggle buttons.

Here is the exact step-by-step user journey:

### Step 1: Framework Deployment (First-time Setup)
The user downloads FusionClip (either cloning the repo or running a docker-compose file).
- If self-hosting locally: Run `docker-compose up -d`. This boots:
  1. The Next.js frontend dashboard (accessible at `http://localhost:3000`).
  2. The FastAPI backend server.
  3. Redis queue and worker.
  4. PostgreSQL database and MinIO storage.

### Step 2: Selecting the Compute backend
Inside the FusionClip Settings Dashboard under **"Generation Source Settings"**, the user sees three options:
1. **API Mode**: Uses Cloud endpoints (e.g. Gemini API, ElevenLabs API). Requirements: Enter personal API keys.
2. **Local GPU Mode**: Runs models directly on the user's host machine. Requirements: A local NVIDIA GPU (minimum 8GB VRAM) and PyTorch runtime.
3. **Google Colab (Bridge Mode)**: Offloads generation tasks to Google's free/pro cloud GPUs (like NVIDIA T4/A100).

---

### Focus: How the Google Colab workflow operates for the User
If the user selects **Google Colab Mode**:

1. **Launch Notebook**:
   - The user clicks the button **"Open Setup Notebook in Google Colab"** in the settings panel. This loads our public notebook template from GitHub.
2. **Execute Colab Cells**:
   - On the Google Colab page, the user logs in and clicks "Run All" (or runs cells sequentially).
   - *What happens inside Colab*:
     - Installs FastAPI, PyTorch, Diffusers, and tunneling software (`cloudflared`).
     - Downloads the targeting generative model (e.g., Stable Diffusion 1.5, XTTS v2, or Flux-schnell). Google's gigabit network pulls these model weights in ~60-90 seconds directly from Hugging Face into the Colab VM.
     - Runs the background tunneling script and spins up the server.
3. **Copy-Paste the Tunnel Engine Link**:
   - The final cell in the notebook prints a message:
     `👉 Copy this URL: https://xxxx.trycloudflare.com` or `https://yyyy.ngrok-free.app`
   - The user copies this link.
4. **Link the Application**:
   - The user returns to the FusionClip Web Dashboard, pastes the tunnel link into the **"Colab Endpoint URL"** field, and clicks **"Connect"**.
   - FusionClip's backend immediately pings the endpoint: `GET https://xxxx.trycloudflare.com/health`.
   - On success, the UI displays: **"Status: Connected (T4 GPU Remote Connected)"**.

---

### Step 3: Media Generation
Once connected, the user goes to the creation workspace (e.g., /generate):

1. **User input**: Selects "Text-to-Image", picks "Google Colab" as the engine, inputs prompt: *"cyberpunk cat piloting a spaceship"*.
2. **Transmission**:
   - The Next.js client submits the form data to the FusionClip FastAPI backend.
   - The backend routes the request to the active Colab endpoint: `POST https://xxxx.trycloudflare.com/txt2img`.
3. **Processing & Feedback**:
   - The Colab GPU draws the image (takes 5-10 seconds for standard diffusion, or 2 seconds for Flux-schnell).
   - Colab base64-encodes the resulting PNG and sends it back in the HTTP response.
4. **Asset Saving**:
   - FusionClip receives the base64 payload, decodes it, uploads the PNG to the MinIO object store, writes the file path and metadata into PostgreSQL, and pushes a websocket update to the UI.
   - The generated cyberpunk cat image pops up in the user's FusionClip app gallery.
