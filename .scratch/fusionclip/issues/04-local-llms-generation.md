Status: resolved
Type: research
Blocked by: None

## Question
How can a user generate audio, photos, and videos using local LLMs/diffusion models, and what are the best libraries/modules to use for this inside the application?

## Answer
To support local generation of audio, photo, and video inside the FusionClip backend, we should leverage standard Python AI/ML libraries running on the host GPU.

Here are the best open-source models, libraries, and integration strategies:

1. **Photo / Image Generation**:
   - **Recommended Models**:
     - *Flux.1 (Schnell/Dev)*: Under active industry use. Flux.1-schnell requires only 4 steps for high-quality images.
     - *Stable Diffusion XL (SDXL)*: Highly mature ecosystem, fast inference, lower memory footprint (can run on 8GB VRAM).
   - **Libraries/Engines**:
     - HuggingFace `diffusers`: The standard python API to load pipelines, apply loras, scheduler settings, and invoke img2img/txt2img operations.
     - ComfyUI API: Run a ComfyUI instance backend-only and execute JSON workflows. Outstanding VRAM management and flexibility.

2. **Audio / Speech / Music Generation**:
   - **Text-to-Speech (TTS) / Voice Cloning**:
     - *Coqui XTTS v2*: Exceptional multilingual voice cloning and speech synthesis. Runs easily via `TTS` library.
     - *ChatTTS*: Extremely realistic conversational speech and natural pacing (e.g. laughter/breaths).
   - **Sound Effects & Music**:
     - *Audiocraft (MusicGen / AudioGen)*: Developed by Meta. MusicGen generates high-quality audio tracks from text descriptions. AudioGen generates sound effects.
   - **Libraries**:
     - Meta's `audiocraft` library for python.
     - `TTS` library by Coqui.

3. **Video Generation**:
   - **Text-to-Video / Image-to-Video**:
     - *Stable Video Diffusion (SVD)*: Outstanding image-to-video capabilities (turns a static photo into a 3-4 second video clip).
     - *CogVideoX* or *HunyuanVideo*: State-of-the-art open-source text-to-video models.
   - **Libraries**:
     - HuggingFace `diffusers` (using `StableVideoDiffusionPipeline`).
     - ComfyUI REST API for complex video rendering chains.

4. **Integration Layer (FastAPI)**:
   - Create a specialized backend router `/generate` with endpoints:
     - `/generate/image` (returns base64 or stores in MinIO and returns filename).
     - `/generate/audio` (returns binary audio stream or WAV file).
     - `/generate/video` (runs asynchronously using Celery, returns a job ID, processes via SVD/CogVideoX, saves MP4, updates client using WebSockets when ready).
