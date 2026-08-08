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
import threading
import requests
import psutil

try:
    import websocket
except ImportError:
    print("Warning: 'websocket-client' package not found. Run 'pip install websocket-client'")
    websocket = None

try:
    import GPUtil
except ImportError:
    GPUtil = None

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("colab_client")

class ColabComputeWorker:
    def __init__(self, server_url, token, poll_interval=5.0, metrics_interval=2.0):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.poll_interval = poll_interval
        self.metrics_interval = metrics_interval
        self.is_running = False
        self.websocket_connected = False
        self.active_task = None
        
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
            metrics["cpu_load"] = psutil.cpu_percent()
            ram = psutil.virtual_memory()
            metrics["ram_used"] = ram.used / (1024 ** 3)  # GB
            metrics["ram_total"] = ram.total / (1024 ** 3)  # GB
            
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
                    self.ws.send(json.dumps(payload))
                except Exception as e:
                    logger.debug(f"Failed to send metrics via WebSocket: {e}")
            else:
                # HTTP fallback
                try:
                    res = requests.post(
                        f"{self.server_url}/api/colab/metrics?token={self.token}",
                        json=metrics,
                        timeout=5.0
                    )
                    if res.status_code != 200:
                        logger.warning(f"HTTP metrics report returned status: {res.status_code}")
                except Exception as e:
                    logger.debug(f"HTTP metrics report exception: {e}")
                    
            time.sleep(self.metrics_interval)

    def execute_task(self, task_id, task_type, parameters):
        """Simulate GPU task execution with progress reporting."""
        logger.info(f"Starting task {task_id} of type: {task_type}")
        self.active_task = f"{task_type} (ID: {task_id})"
        
        try:
            steps = 5
            for i in range(1, steps + 1):
                percent = int((i / steps) * 100)
                time.sleep(1.0) # Simulate GPU load
                
                # Send progress update
                self.report_progress(task_id, percent)
                
            # Send completion
            output_payload = {
                "url": f"{self.server_url}/api/storage/file/mock_colab_output_{int(time.time())}.png",
                "message": f"Successfully completed {task_type} via Google Colab."
            }
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
                self.ws.send(json.dumps(payload))
                return
            except Exception as e:
                logger.warning(f"Failed sending update via WS: {e}. Trying HTTP fallback.")
        
        # HTTP fallback
        try:
            requests.post(
                f"{self.server_url}/api/colab/tasks/update?token={self.token}",
                json={
                    "task_id": payload["task_id"],
                    "status": "COMPLETED" if payload["type"] == "task_complete" else ("FAILED" if payload["type"] == "task_failed" else "PROCESSING"),
                    "progress": payload.get("percent", 100),
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
                        timeout=5.0
                    )
                    if res.status_code == 200:
                        data = res.json()
                        task = data.get("task")
                        if task:
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
    args = parser.parse_args()
    
    worker = ColabComputeWorker(server_url=args.url, token=args.token)
    try:
        worker.start()
    except KeyboardInterrupt:
        logger.info("Shutting down Colab worker...")
        worker.stop()
