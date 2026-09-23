#!/usr/bin/env python3
"""
FusionClip Google Colab Compute Connector Client
This script runs in the Google Colab environment and establishes a websocket/HTTP 
connection back to the FusionClip server to act as a remote GPU worker.
"""

import os
import sys
import time
import json
import logging
import argparse
import re
import tempfile
import threading
import requests

from typing import Optional, Any, Callable

try:
    import psutil
except ImportError:
    psutil = None

try:
    import websocket
except ImportError:
    print("Warning: 'websocket-client' package not found. Run 'pip install websocket-client'")
    websocket = None

try:
    import GPUtil
except ImportError:
    GPUtil = None

try:
    from PIL import Image, ImageDraw
    has_pil = True
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    has_pil = False

# Minimal 1x1 transparent PNG fallback if PIL is missing
MINIMAL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00"
    b"\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TaskHandlerRegistry:
    """Pluggable registry mapping task types to execution handler functions."""

    def __init__(self):
        self._handlers = {}

    def register(self, task_type: str, handler_fn):
        self._handlers[task_type] = handler_fn

    def get(self, task_type: str):
        return self._handlers.get(task_type)

    def has_handler(self, task_type: str) -> bool:
        return task_type in self._handlers

    def execute(self, task_type: str, task_id: str, parameters: Optional[dict], report_progress, upload_artifact):
        parameters = parameters or {}
        handler = self.get(task_type)
        if not handler:
            raise ValueError(f"No handler registered for task type: '{task_type}'")
        return handler(task_id, parameters, report_progress, upload_artifact)


default_registry = TaskHandlerRegistry()
_cached_pipe = None


def register_handler(task_type: str, registry: Optional[TaskHandlerRegistry] = None):
    reg = registry or default_registry
    def decorator(fn):
        reg.register(task_type, fn)
        return fn
    return decorator


def make_fake_png_artifact(task_id: str, prompt: str = "") -> str:
    """Create a real on-disk PNG file for fake/offline test execution."""
    prompt = prompt or ""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(task_id))
    fd, path = tempfile.mkstemp(prefix=f"colab_fake_{safe_id}_", suffix=".png")
    os.close(fd)
    if has_pil and Image is not None and ImageDraw is not None:
        img = Image.new("RGB", (256, 256), color=(40, 50, 75))
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 246, 246], outline=(100, 200, 255), width=2)
        text = f"FusionClip Colab\nTask: {safe_id[:12]}\n{prompt[:30]}"
        draw.text((20, 100), text, fill=(255, 255, 255))
        img.save(path, format="PNG")
    else:
        with open(path, "wb") as f:
            f.write(MINIMAL_PNG_BYTES)
    return path


def builtin_image_generation_handler(task_id, parameters, report_progress, upload_artifact):
    """Real SDXL diffusion handler with fallback error if diffusers/torch unavailable."""
    parameters = parameters or {}
    prompt = parameters.get("prompt", "")
    steps = int(parameters.get("steps", 20))
    scale = float(parameters.get("scale", 0.0))

    try:
        import torch
        from diffusers import AutoPipelineForText2Image
    except ImportError as e:
        raise RuntimeError(f"Cannot execute real image_generation: diffusers/torch not installed: {e}")

    report_progress(10)
    global _cached_pipe
    if _cached_pipe is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _cached_pipe = AutoPipelineForText2Image.from_pretrained(
            "stabilityai/sdxl-turbo",
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            variant="fp16" if device == "cuda" else None
        ).to(device)

    pipe = _cached_pipe
    report_progress(40)
    img = pipe(prompt=prompt, num_inference_steps=max(1, min(steps, 4)), guidance_scale=scale).images[0]

    report_progress(80)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(task_id))
    fd, path = tempfile.mkstemp(prefix=f"colab_sdxl_{safe_id}_", suffix=".png")
    os.close(fd)
    try:
        img.save(path, format="PNG")
        report_progress(90)
        upload_res = upload_artifact(path)
        report_progress(100)
        return upload_res
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


# Register default real handlers
default_registry.register("image_generation", builtin_image_generation_handler)

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("colab_client")

class ColabComputeWorker:
    def __init__(self, server_url, token, poll_interval=5.0, metrics_interval=2.0, fake_mode=False, registry=None):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.poll_interval = poll_interval
        self.metrics_interval = metrics_interval
        self.fake_mode = fake_mode
        self.registry = registry or default_registry
        self.is_running = False
        self.websocket_connected = False
        self.active_task = None
        self._gpu_lock = threading.Lock()
        self._ws_lock = threading.Lock()
        
        # Determine endpoints
        if self.server_url.startswith("https://"):
            self.ws_url = self.server_url.replace("https://", "wss://") + f"/api/ws/colab?token={token}"
        elif self.server_url.startswith("http://"):
            self.ws_url = self.server_url.replace("http://", "ws://") + f"/api/ws/colab?token={token}"
        else:
            # Assume local/raw domain
            self.ws_url = f"ws://{self.server_url}/api/ws/colab?token={token}"
            self.server_url = f"http://{self.server_url}"

    def get_system_metrics(self):
        """Read GPU VRAM, system RAM, and CPU/task usage."""
        metrics = {
            "vram_used": 0.0,
            "vram_total": 0.0,
            "ram_used": 0.0,
            "ram_total": 0.0,
            "cpu_load": 0.0,
            "active_task": self.active_task
        }
        
        try:
            # CPU and RAM load
            if psutil:
                metrics["cpu_load"] = psutil.cpu_percent()
                ram = psutil.virtual_memory()
                metrics["ram_used"] = ram.used / (1024 ** 3)  # GB
                metrics["ram_total"] = ram.total / (1024 ** 3)  # GB
            else:
                metrics["cpu_load"] = 0.0
                metrics["ram_used"] = 1.0
                metrics["ram_total"] = 16.0
            
            # GPU stats
            if GPUtil:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    metrics["vram_used"] = gpu.memoryUsed / 1024.0  # GB
                    metrics["vram_total"] = gpu.memoryTotal / 1024.0  # GB
            else:
                # Mock GPU info for testing/local setups where GPUtil is absent
                metrics["vram_used"] = 0.0
                metrics["vram_total"] = 16.0
        except Exception as e:
            logger.error(f"Error reading system metrics: {e}")
            
        return metrics

    def metrics_reporter_loop(self):
        """Periodically reports system utilization to FusionClip."""
        while self.is_running:
            metrics = self.get_system_metrics()
            
            if self.websocket_connected and hasattr(self, 'ws') and self.ws:
                try:
                    payload = {"type": "metrics", **metrics}
                    with self._ws_lock:
                        self.ws.send(json.dumps(payload))
                except Exception as e:
                    logger.debug(f"Failed to send metrics via WebSocket: {e}")
            else:
                # HTTP fallback
                try:
                    res = requests.post(
                        f"{self.server_url}/api/colab/metrics?token={self.token}",
                        headers={"Authorization": f"Bearer {self.token}"},
                        json=metrics,
                        timeout=5.0
                    )
                    if res.status_code != 200:
                        logger.warning(f"HTTP metrics report returned status: {res.status_code}")
                except Exception as e:
                    logger.debug(f"HTTP metrics report exception: {e}")
                    
            time.sleep(self.metrics_interval)

    def upload_artifact(self, file_path: str, folder: str = "") -> dict:
        """Upload generated media file to FusionClip /api/storage/upload endpoint."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Generated artifact not found: {file_path}")

        url = f"{self.server_url}/api/storage/upload"
        params = {}
        if folder:
            params["folder"] = folder

        filename = os.path.basename(file_path)
        content_type = "image/png"
        if filename.lower().endswith(".jpg") or filename.lower().endswith(".jpeg"):
            content_type = "image/jpeg"
        elif filename.lower().endswith(".mp4"):
            content_type = "video/mp4"
        elif filename.lower().endswith(".wav") or filename.lower().endswith(".mp3"):
            content_type = "audio/mpeg"
        elif filename.lower().endswith(".txt"):
            content_type = "text/plain"

        with open(file_path, "rb") as f:
            files = {"file": (filename, f, content_type)}
            response = requests.post(url, params=params, files=files, timeout=60.0)

        if response.status_code != 200:
            raise RuntimeError(f"Storage upload failed ({response.status_code}): {response.text}")

        data = response.json()
        logger.info(f"Artifact uploaded to storage: {data.get('url')}")
        return data

    def execute_task(self, task_id, task_type, parameters):
        """Execute task via handler registry or fake mode with real artifact upload."""
        logger.info(f"Starting task {task_id} of type: {task_type}")
        
        with self._gpu_lock:
            self.active_task = f"{task_type} (ID: {task_id})"
            try:
                def on_progress(percent):
                    self.report_progress(task_id, percent)

                if self.fake_mode:
                    on_progress(25)
                    prompt = (parameters.get("prompt") or "") if isinstance(parameters, dict) else ""
                    artifact_path = make_fake_png_artifact(task_id, prompt)
                    try:
                        on_progress(75)
                        upload_res = self.upload_artifact(artifact_path)
                        on_progress(100)
                        output_payload = {
                            "url": upload_res.get("url"),
                            "filename": upload_res.get("filename"),
                            "path": upload_res.get("path"),
                            "message": f"Successfully completed {task_type} (fake mode)."
                        }
                    finally:
                        if os.path.exists(artifact_path):
                            try:
                                os.remove(artifact_path)
                            except OSError:
                                pass
                elif self.registry.has_handler(task_type):
                    result = self.registry.execute(
                        task_type,
                        task_id,
                        parameters,
                        report_progress=on_progress,
                        upload_artifact=self.upload_artifact
                    )
                    if isinstance(result, dict) and "url" in result:
                        output_payload = result
                    elif isinstance(result, dict) and "file_path" in result:
                        upload_res = self.upload_artifact(result["file_path"])
                        output_payload = {
                            "url": upload_res.get("url"),
                            "filename": upload_res.get("filename"),
                            "path": upload_res.get("path")
                        }
                    else:
                        output_payload = {
                            "output": result,
                            "message": f"Successfully completed {task_type} via Google Colab."
                        }
                else:
                    raise ValueError(f"No handler registered for task type: '{task_type}'")

                self.report_completion(task_id, output_payload)
                logger.info(f"Successfully completed task {task_id}")
            except Exception as e:
                logger.error(f"Error executing task {task_id}: {e}")
                self.report_failure(task_id, str(e))
            finally:
                self.active_task = None

    def report_progress(self, task_id, percent):
        payload = {
            "type": "task_progress",
            "task_id": task_id,
            "percent": percent,
            "status": "PROCESSING"
        }
        self.send_update(payload)

    def report_completion(self, task_id, output):
        payload = {
            "type": "task_complete",
            "task_id": task_id,
            "output": output
        }
        self.send_update(payload)

    def report_failure(self, task_id, error_message):
        payload = {
            "type": "task_failed",
            "task_id": task_id,
            "error": error_message
        }
        self.send_update(payload)

    def send_update(self, payload):
        if self.websocket_connected and hasattr(self, 'ws') and self.ws:
            try:
                with self._ws_lock:
                    self.ws.send(json.dumps(payload))
                return
            except Exception as e:
                logger.warning(f"Failed sending update via WS: {e}. Trying HTTP fallback.")
        
        # HTTP fallback
        try:
            progress_val = payload.get("percent", 100 if payload["type"] == "task_complete" else 0)
            requests.post(
                f"{self.server_url}/api/colab/tasks/update?token={self.token}",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "task_id": payload["task_id"],
                    "status": "COMPLETED" if payload["type"] == "task_complete" else ("FAILED" if payload["type"] == "task_failed" else "PROCESSING"),
                    "progress": progress_val,
                    "output": payload.get("output"),
                    "error": payload.get("error")
                },
                timeout=5.0
            )
        except Exception as e:
            logger.error(f"Failed to send task update via HTTP fallback: {e}")

    def run_websocket_loop(self):
        """Runs the main WebSocket loop with reconnection logic."""
        if not websocket:
            logger.error("Websocket client library not installed. WebSockets disabled.")
            return

        while self.is_running:
            try:
                logger.info(f"Connecting to WebSocket: {self.ws_url.split('?')[0]}")
                
                # Setup WS callbacks
                def on_open(ws):
                    logger.info("WebSocket connection established")
                    self.websocket_connected = True
                    
                def on_message(ws, message):
                    try:
                        logger.info(f"Received WebSocket message: {message}")
                        payload = json.loads(message)
                        if payload.get("type") == "task_dispatch":
                            task_id = payload.get("task_id")
                            task_type = payload.get("task_type")
                            parameters = payload.get("parameters", {})
                            
                            # Run task in a separate worker thread
                            threading.Thread(
                                target=self.execute_task,
                                args=(task_id, task_type, parameters),
                                daemon=True
                            ).start()
                    except Exception as err:
                        logger.error(f"Error handling inbound WebSocket message: {err}")

                def on_error(ws, error):
                    logger.error(f"WebSocket error occurred: {error}")

                def on_close(ws, close_status_code, close_msg):
                    logger.info(f"WebSocket connection closed: {close_msg} ({close_status_code})")
                    self.websocket_connected = False

                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close
                )
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"WebSocket wrapper loop exception: {e}")
                self.websocket_connected = False
            
            # Reconnection backoff
            logger.info("Retrying WebSocket integration in 5 seconds...")
            time.sleep(5)

    def run_http_polling_loop(self):
        """Fallback polling runner checking for jobs when WebSocket is down."""
        logger.info("Starting HTTP polling fallback scheduler loop")
        while self.is_running:
            if not self.websocket_connected:
                try:
                    res = requests.get(
                        f"{self.server_url}/api/colab/tasks/pending?token={self.token}",
                        headers={"Authorization": f"Bearer {self.token}"},
                        timeout=5.0
                    )
                    if res.status_code == 200:
                        data = res.json()
                        task = data.get("task") if "task" in data else data
                        if task and task.get("task_id"):
                            task_id = task.get("task_id")
                            task_type = task.get("task_type")
                            parameters = task.get("parameters", {})
                            
                            self.execute_task(task_id, task_type, parameters)
                except Exception as e:
                    logger.error(f"HTTP polling task checker loop exception: {e}")
            
            time.sleep(self.poll_interval)

    def start(self):
        self.is_running = True
        
        # Start metrics thread
        self.metrics_thread = threading.Thread(target=self.metrics_reporter_loop, daemon=True)
        self.metrics_thread.start()
        
        # Start HTTP polling loop in secondary thread as fallback
        self.http_poll_thread = threading.Thread(target=self.run_http_polling_loop, daemon=True)
        self.http_poll_thread.start()
        
        # WebSocket runs on the main thread and reconnection will loop indefinitely
        if websocket:
            self.run_websocket_loop()
        else:
            # If no websocket library, fallback to HTTP poll blocking main thread
            self.http_poll_thread.join()

    def stop(self):
        self.is_running = False
        if hasattr(self, 'ws') and self.ws:
            self.ws.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FusionClip Colab Compute Connector client")
    parser.add_argument("--url", required=True, help="FusionClip Server Base URL (or Tunnel URL)")
    parser.add_argument("--token", required=True, help="FusionClip authentication token")
    parser.add_argument("--fake", action="store_true", help="Run with fake handler mode for offline testing")
    args = parser.parse_args()
    
    worker = ColabComputeWorker(server_url=args.url, token=args.token, fake_mode=args.fake)
    try:
        worker.start()
    except KeyboardInterrupt:
        logger.info("Shutting down Colab worker...")
        worker.stop()
