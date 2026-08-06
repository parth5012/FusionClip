Status: resolved
Type: research
Blocked by: None

## Question
How does Magnific AI work internally and what underlying models/technologies does it use for image enhancement/upscaling?

## Answer
Magnific AI is a generative upscaler built on top of Generative Latent Diffusion Models (like SDXL or Flux) and ControlNet. Unlike traditional deterministic super-resolution (ESRGAN, SwinIR) which simply blends pixels and can produce a plastic-like texture, generative upscaling actually "hallucinates" high-frequency textures (like skin pores, fabric weaves, wood bark) while maintaining spatial coherence.

The internal workflow of a Magnific-style pipeline consists of:
1. **Pre-Upscaling**: First, the input low-resolution image is upscaled to the target resolution using a fast, high-quality traditional upscaler (like Real-ESRGAN or SwinIR/DAT) to fix blurriness and establish a base image.
2. **Tile Partitioning**: For large output sizes (e.g. 4k or 8k), the image is split into overlapping grid tiles (typically 512x512 or 1024x1024 pixels) to fit inside GPU VRAM limits.
3. **ControlNet Tile + Img2Img**:
   - Each tile is run through a Latent Diffusion Model (typically SDXL or Flux.1-dev) in an Image-to-Image (img2img) pass.
   - A **ControlNet Tile** model is applied. ControlNet Tile acts as a strong structural guidance, preventing the diffusion model from changing the overall shapes, composition, or layout of the original tiles, even at higher denoising strengths.
   - A low to moderate denoising strength (e.g. 0.1 to 0.4) is used to draw fine details and textures onto the pre-upscaled tiles.
4. **Prompt Conditioning**: The upscaling pass is conditioned on details prompts (e.g., "ultra high resolution, highly detailed pores, professional photo, sharp focus") to guide what kind of textures are hallucinated.
5. **Denoising & Hallucination Sliders**:
   - *Creativity Slider*: Directly corresponds to the **Denoising Strength** parameter in the diffusion process. Higher creativity = higher denoising strength (e.g., 0.35), letting the model create new elements. Lower creativity = lower denoising (e.g., 0.15), keeping it closer to original details.
   - *Resemblance Slider*: Controls the **guidance weight** of the ControlNet Tile model. Higher resemblance increases ControlNet weight (e.g., 1.2), making it restrict changes.
6. **Tiled Blending**: The processed tiles are merged back using overlapping feathering (e.g., using algorithms like MultiDiffusion or Ultimate SD Upscale node in ComfyUI) to prevent grid seams.

Open-source alternative implementation: Use **Stable Diffusion XL** or **Flux.1-dev** with **ControlNet-Tile** (or ControlNet-Union / IP-Adapter-Tile) using Python `diffusers` or ComfyUI headlessly.
