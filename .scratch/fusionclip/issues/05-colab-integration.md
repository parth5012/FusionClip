Status: resolved
Type: research
Blocked by: None

## Question
How can we enable a feature where users run local LLMs/diffusion models on Google Colab, expose it via a host/tunnel, point the app to it, and have the app generate and receive images?

## Answer
This feature utilizes Google Colab as an ephemeral GPU compute node. It requires two pieces: a Python server notebook running on Google Colab that establishes a public tunnel, and a connection configuration interface in the main FusionClip application.

Here is the implementation protocol:

1. **The Google Colab Notebook (Server-side)**:
   - The user runs a Colab Notebook that installs python dependencies: `pip install fastapi uvicorn diffusers transformers pyngrok` (or downloads a ComfyUI setup).
   - The notebook starts a lightweight FastAPI script (or runs ComfyUI with the `--api` flag).
   - Use a tunneling daemon to expose localhost port (e.g. `8000` or `8188`) to the public internet:
     - **Cloudflare Tunnels (Quickest, no token needed)**:
       ```python
       # Download cloudflared binary
       !wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
       !dpkg -i cloudflared-linux-amd64.deb
       # Run tunnel in background and dump output to find the *.trycloudflare.com url
       import subprocess
       import re
       import time
       
       proc = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://localhost:8000"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
       time.sleep(5) # Let it connect
       # Scan output for url
       for line in proc.stdout:
           if ".trycloudflare.com" in line:
               url = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare.com", line).group()
               print("Public Colab Endpoint URL:", url)
               break
       ```
     - **ngrok (Very stable, requires user ngrok authtoken)**:
       ```python
       from pyngrok import ngrok
       ngrok.set_auth_token("USER_NGROK_TOKEN")
       tunnel = ngrok.connect(8000)
       print("Public Colab Endpoint URL:", tunnel.public_url)
       ```

2. **The FastAPI app running inside Colab**:
   It runs text/image generation loops using HuggingFace Diffusers:
   ```python
   from fastapi import FastAPI
   from pydantic import BaseModel
   from diffusers import StableDiffusionPipeline
   import torch
   import io
   import base64

   app = FastAPI()
   pipe = StableDiffusionPipeline.from_pretrained("runwayml/stable-diffusion-v1-5", torch_dtype=torch.float16).to("cuda")

   class GenerateRequest(BaseModel):
       prompt: str

   @app.post("/txt2img")
   def txt2img(req: GenerateRequest):
       image = pipe(req.prompt).images[0]
       buffered = io.BytesIO()
       image.save(buffered, format="PNG")
       img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
       return {"image": img_str}
   ```

3. **The FusionClip Web Application (Client-side)**:
   - Under User Settings, add a "Remote Compute Endpoint" field (e.g. `colab_endpoint_url`).
   - When generating an image, if `colab_endpoint_url` is provided and active, the backend (or frontend directly) sends a POST request:
     `POST {colab_endpoint_url}/txt2img` with body `{"prompt": "User input prompt"}`.
   - The app receives the base64 string, converts it to an image/stores it in MinIO, and renders it to the user.
