import time
import subprocess
import traceback
import sys
import json
import redis
from datetime import datetime, timezone
from app.celery_app import celery
from app.storage import upload_object, generate_url
from app.upscaler import TileUpscaler, calculate_tile_size
from app.scratchpad import scratchpad
from app.database import SessionLocal
from app.models import Task, MediaAsset
from app.config import settings
import logging

logger = logging.getLogger(__name__)

TRANSIENT_ERRORS = ('out of memory', 'oom', 'timeout', 'timeouterror',
                     'connectionerror', 'connection', '429', '503', 'temporarily')
PERMANENT_ERRORS = ('invalid', 'validation', 'bad parameter', 'not found',
                    '404', '403', 'forbidden', 'unauthorized', '401',
                    'unsupported', 'corrupt', 'malformed')


def exponential_backoff(retry_count: int) -> int:
    return (2 ** retry_count) * 60


def is_transient_error(error_msg: str) -> bool:
    if not error_msg:
        return False
    lower = error_msg.lower()
    if any(pe in lower for pe in PERMANENT_ERRORS):
        return False
    return any(te in lower for te in TRANSIENT_ERRORS)


def categorize_error(error_msg: str) -> str:
    if not error_msg:
        return 'runtime'
    lower = error_msg.lower()
    if 'out of memory' in lower or 'oom' in lower or 'memoryerror' in lower:
        return 'OOM'
    if 'timeout' in lower or 'timed out' in lower:
        return 'timeout'
    if any(v in lower for v in ('invalid', 'validation', 'bad parameter', 'unsupported')):
        return 'validation'
    return 'runtime'


def _handle_task_failure(task_id: str, error: Exception, retry_count: int, max_retries: int):
    error_msg = str(error)
    tb_str = traceback.format_exc()
    error_type = categorize_error(error_msg)
    transient = is_transient_error(error_msg)

    db = SessionLocal()
    try:
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task:
            db_task.error = error_msg
            db_task.error_type = error_type
            db_task.traceback = tb_str
            db_task.retry_count = retry_count
            db_task.max_retries = max_retries
            if transient and retry_count < max_retries:
                db_task.status = 'PENDING_RETRY'
            else:
                db_task.status = 'FAILED'
            db.commit()
    finally:
        db.close()

    redis_client.publish("task_updates", json.dumps({
        "task_id": task_id,
        "status": 'PENDING_RETRY' if (transient and retry_count < max_retries) else 'FAILED',
        "progress": 0,
        "error": error_msg,
        "error_type": error_type,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "traceback": tb_str
    }))

    if transient and retry_count < max_retries:
        logger.info(f"Task {task_id} transient error ({error_type}), retry {retry_count}/{max_retries}")
    else:
        logger.error(f"Task {task_id} permanent failure ({error_type}): {error_msg}")

    return transient and retry_count < max_retries


def update_task_retry(db_task: Task, retry_count: int, db) -> None:
    """Update retry tracking fields on task."""
    db_task.retry_count = retry_count
    db_task.last_retry_at = datetime.now(timezone.utc)
    db.commit()


def parse_duration(file_path: str) -> float:
    """Get duration of media file in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Failed to parse duration {file_path}: {e}")
        return 0.0


def run_ffmpeg_with_progress(cmd, duration: float, task_id: str, celery_task=None) -> None:
    """Run FFmpeg command with subprocess and update progress via Redis/DB."""
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")

    time_regex = __import__('re').compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

    db = SessionLocal()
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )

        while True:
            line = process.stdout.readline()
            if not line:
                break

            match = time_regex.search(line)
            if match and duration > 0:
                hours, minutes, seconds, ms = map(int, match.groups())
                current_time = hours * 3600 + minutes * 60 + seconds + ms / 100.0
                percent = min(int((current_time / duration) * 100), 99)

                update_payload = {
                    "task_id": task_id,
                    "status": "PROGRESS",
                    "progress": percent,
                    "error": None
                }
                redis_client.publish("task_updates", json.dumps(update_payload))

                try:
                    db_task = db.query(Task).filter(Task.task_id == task_id).first()
                    if db_task:
                        db_task.progress = percent
                        db.commit()
                except Exception as e:
                    logger.error(f"Failed to update progress for task {task_id}: {e}")

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg process encountered error: {e}")
        raise
    finally:
        db.close()

def _handle_task_failure(task_id: str, e: Exception, max_retries: int) -> bool:
    """Handle task failure retry logic. Returns True if retry scheduled."""
    error_msg = str(e)
    tb = traceback.format_exc()
    error_type = categorize_error(error_msg)

    db = SessionLocal()
    try:
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if not db_task:
            return False

        current_retry = db_task.retry_count

        if current_retry < max_retries and is_transient_error(error_msg):
            new_retry_count = current_retry + 1
            countdown = exponential_backoff(new_retry_count)
            logger.info(
                f"Transient error for task {task_id}, "
                f"scheduling retry {new_retry_count}/{max_retries} in {countdown}s"
            )
            update_task_retry(db_task, new_retry_count, db)
            db_task.status = "RETRYING"
            db.commit()

            redis_client.publish("task_updates", json.dumps({
                "task_id": task_id,
                "status": "RETRYING",
                "progress": 0,
                "error": f"Retry {new_retry_count}/{max_retries} in {countdown}s: {error_msg}",
                "retry_count": new_retry_count,
                "max_retries": max_retries,
                "error_type": error_type
            }))
            return True
        else:
            db_task.status = "FAILED"
            db_task.error = error_msg
            db_task.traceback = tb
            db_task.error_type = error_type
            db.commit()

            redis_client.publish("task_updates", json.dumps({
                "task_id": task_id,
                "status": "FAILED",
                "progress": 0,
                "error": error_msg,
                "traceback": tb,
                "retry_count": current_retry,
                "max_retries": max_retries,
                "error_type": error_type
            }))
            return False
    finally:
        db.close()


# Fast task endpoint
@celery.task(bind=True, name="app.tasks.process_media_fast", max_retries=3)
def process_media_fast(self, object_name: str, task_type: str = "thumbnail"):
    logger.info(f"Processing fast task: {task_type} {object_name}")
    task_id = self.request.id
    retry_count = self.request.retries

    db = SessionLocal()
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        db_task = Task(task_id=task_id, name=task_type, status="PROCESSING", progress=0,
                       retry_count=retry_count, max_retries=3)
        db.add(db_task)
        db.commit()
    else:
        db_task.retry_count = retry_count
        db_task.status = "PROCESSING"
        db.commit()
    db.close()

    try:
        steps = 4
        for i in range(1, steps + 1):
            time.sleep(1.0)
            percent = int((i / steps) * 100)

            self.update_state(
                state="PROGRESS",
                meta={"percent": percent, "status": f"Running fast step {i}/{steps}"}
            )

            update_payload = {
                "task_id": task_id,
                "status": "PROCESSING" if percent < 100 else "COMPLETED",
                "progress": percent,
                "error": None
            }
            redis_client.publish("task_updates", json.dumps(update_payload))

        db = SessionLocal()
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task:
            db_task.status = "PROCESSING" if percent < 100 else "COMPLETED"
            db_task.progress = percent
            db.commit()
        db.close()

        processed_name = f"processed/thumb_{object_name.split('/')[-1]}"
        simulated_media = b"Simulated thumbnail content bytes."
        upload_success = upload_object(simulated_media, processed_name, content_type="image/png")

        return {
            "status": "COMPLETED",
            "task_id": task_id,
            "original_object": object_name,
            "processed_url": generate_url(processed_name) if upload_success else None
        }

    except Exception as e:
        logger.error(f"Error executing fast task {task_id}: {e}")
        should_retry = _handle_task_failure(task_id, e, max_retries=3)
        if should_retry:
            raise self.retry(
                exc=e,
                countdown=exponential_backoff(self.request.retries + 1)
            )
        raise

# Heavy task queue endpoint
@celery.task(bind=True, name="app.tasks.process_media_heavy", max_retries=3)
def process_media_heavy(self, object_name: str, task_type: str = "transcode"):
    logger.info(f"Processing heavy task: {task_type} {object_name}")
    task_id = self.request.id
    retry_count = self.request.retries

    is_colab = redis_client.get("colab:connected") == b"true"
    if is_colab:
        logger.info(f"Colab worker detected! Offloading heavy task {task_type} {object_name}")
        task_payload = {
            "type": "task_dispatch",
            "task_id": task_id,
            "task_type": task_type,
            "parameters": {
                "object_name": object_name,
                "input_url": generate_url(object_name)
            }
        }

        redis_client.publish("colab_dispatches", json.dumps(task_payload))
        redis_client.rpush("colab_pending_tasks_http", json.dumps(task_payload))
        redis_client.expire("colab_pending_tasks_http", 3600)

        result_key = f"colab_task_result:{task_id}"
        timeout = 120
        start_time = time.time()
        while time.time() - start_time < timeout:
            res_data = redis_client.get(result_key)
            if res_data:
                res = json.loads(res_data)

                db = SessionLocal()
                try:
                    db_task = db.query(Task).filter(Task.task_id == task_id).first()
                    if res.get("status") == "SUCCESS":
                        output = res.get("output", {})
                        processed_url = output.get("url", "")
                        processed_name = output.get("filename", f"processed_{object_name.split('/')[-1]}")

                        if db_task:
                            db_task.status = "COMPLETED"
                            db_task.progress = 100
                            db.commit()

                        redis_client.publish("task_updates", json.dumps({
                            "task_id": task_id,
                            "status": "COMPLETED",
                            "progress": 100,
                            "error": None
                        }))

                        return {
                            "status": "COMPLETED",
                            "task_id": task_id,
                            "original_object": object_name,
                            "processed_url": processed_url
                        }
                    else:
                        error_msg = res.get("error", "Task failed in Colab")
                        if db_task:
                            db_task.status = "FAILED"
                            db_task.error = error_msg
                            db.commit()

                        redis_client.publish("task_updates", json.dumps({
                            "task_id": task_id,
                            "status": "FAILED",
                            "progress": 0,
                            "error": error_msg
                        }))
                        raise Exception(error_msg)
                finally:
                    db.close()
            time.sleep(0.5)

        db = SessionLocal()
        try:
            db_task = db.query(Task).filter(Task.task_id == task_id).first()
            if db_task:
                db_task.status = "FAILED"
                db_task.error = "Execution timed out waiting for Colab worker response"
                db.commit()
        finally:
            db.close()

        redis_client.publish("task_updates", json.dumps({
            "task_id": task_id,
            "status": "FAILED",
            "progress": 0,
            "error": "Colab execution timed out"
        }))
        raise TimeoutError("Colab execution timed out")

            timeout = 120
            start_time = time.time()
            while time.time() - start_time < timeout:
                res_data = redis_client.get(result_key)
                if res_data:
                    res = json.loads(res_data)
                    db = SessionLocal()
                    try:
                        db_task = db.query(Task).filter(Task.task_id == task_id).first()
                        if res.get("status") == "SUCCESS":
                            output = res.get("output", {})
                            processed_url = output.get("url", "")
                            processed_name = output.get("filename", f"processed_{object_name.split('/')[-1]}")
                            if db_task:
                                db_task.status = "COMPLETED"
                                db_task.progress = 100
                                db.commit()
                            redis_client.publish("task_updates", json.dumps({
                                "task_id": task_id, "status": "COMPLETED",
                                "progress": 100, "error": None
                            }))
                            return {
                                "status": "COMPLETED", "task_id": task_id,
                                "original_object": object_name, "processed_url": processed_url
                            }
                        else:
                            error_msg = res.get("error", "Task failed on Colab")
                            if db_task:
                                db_task.status = "FAILED"
                                db_task.error = error_msg
                                db.commit()
                            redis_client.publish("task_updates", json.dumps({
                                "task_id": task_id, "status": "FAILED",
                                "progress": 0, "error": error_msg
                            }))
                            raise Exception(error_msg)
                    finally:
                        db.close()
                time.sleep(0.5)

            raise TimeoutError("Colab execution timed out")

        return _original_process_media_heavy(self, object_name, task_type)
    except Exception as e:
        should_retry = _handle_task_failure(task_id, e, retry_count, 3)
        if should_retry:
            countdown = exponential_backoff(retry_count)
            raise self.retry(countdown=countdown, exc=e)
        raise


def _original_process_media_heavy(self, object_name: str, task_type: str = "transcode"):
    logger.info(f"Processing heavy task: {task_type} {object_name}")
    task_id = self.request.id

    temp_in = scratchpad.get_temp_path(suffix="_in.mp4")
    temp_out = scratchpad.get_temp_path(suffix="_out.mp4")

    db = SessionLocal()
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        db_task = Task(task_id=task_id, name=task_type, status="PROCESSING", progress=0)
        db.add(db_task)
        db.commit()
    db.close()

    from app.storage import s3_client
    try:
        s3_client.download_file(settings.MINIO_BUCKET_NAME, object_name, str(temp_in))

        duration = parse_duration(str(temp_in))
        if duration == 0.0:
            duration = 10.0

        cmd = ["ffmpeg", "-y", "-i", str(temp_in), "-vcodec", "libx264", "-acodec", "aac", str(temp_out)]
        run_ffmpeg_with_progress(cmd, duration, task_id, celery_task=self)

        processed_name = f"processed/{object_name.split('/')[-1]}"
        with open(str(temp_out), "rb") as f:
            upload_success = upload_object(f.read(), processed_name, content_type="video/mp4")

        db = SessionLocal()
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task:
            db_task.status = "COMPLETED"
            db_task.progress = 100
            db.commit()
        db.close()

        redis_client.publish("task_updates", json.dumps({
            "task_id": task_id,
            "status": "COMPLETED",
            "progress": 100,
            "error": None
        }))

        return {
            "status": "COMPLETED",
            "task_id": task_id,
            "original_object": object_name,
            "processed_url": generate_url(processed_name) if upload_success else None
        }

    except Exception as e:
        logger.error(f"Error executing heavy task {task_id}: {e}")
        should_retry = _handle_task_failure(task_id, e, max_retries=3)
        if should_retry:
            raise self.retry(
                exc=e,
                countdown=exponential_backoff(self.request.retries + 1)
            )
        raise
    finally:
        scratchpad.remove_path(temp_in)
        scratchpad.remove_path(temp_out)


# Backward compatibility
@celery.task(bind=True)
def process_multimedia_task(self, object_name: str, task_type: str = "transcode"):
    if task_type in ["thumbnail", "waveform"]:
        return process_media_fast(object_name, task_type)
    else:
        return process_media_heavy(object_name, task_type)


@celery.task(bind=True, name="app.tasks.process_upscale_task")
def process_upscale_task(self, task_id: str, object_name: str, params: dict):
    logger.info(f"Starting upscale task: {task_id} for {object_name} with params {params}")
    
    # Check Colab availability
    is_colab = redis_client.get("colab:connected") == b"true"
    if is_colab:
        logger.info(f"Colab worker detected! Offloading upscale task {task_id}")
        task_payload = {
            "type": "task_dispatch",
            "task_id": task_id,
            "task_type": "upscale",
            "parameters": {
                "object_name": object_name,
                "input_url": generate_url(object_name),
                **params
            }
        }
        redis_client.publish("colab_dispatches", json.dumps(task_payload))
        redis_client.rpush("colab_pending_tasks_http", json.dumps(task_payload))
        redis_client.expire("colab_pending_tasks_http", 3600)
        
        # Wait for result in Redis
        result_key = f"colab_task_result:{task_id}"
        timeout = 180
        start_time = time.time()
        while time.time() - start_time < timeout:
            res_data = redis_client.get(result_key)
            if res_data:
                res = json.loads(res_data)
                
                db = SessionLocal()
                try:
                    db_task = db.query(Task).filter(Task.task_id == task_id).first()
                    if res.get("status") == "SUCCESS":
                        output = res.get("output", {})
                        processed_url = output.get("url", "")
                        processed_name = output.get("filename", f"processed_{object_name.split('/')[-1]}")
                        
                        if db_task:
                            db_task.status = "COMPLETED"
                            db_task.progress = 100
                        db.commit()
                        
                        redis_client.publish("task_updates", json.dumps({
                            "task_id": task_id,
                            "status": "COMPLETED",
                            "progress": 100,
                            "error": None
                        }))
                        
                        # Create MediaAsset record
                        asset = MediaAsset(
                            title=f"Upscaled: {object_name.split('/')[-1]}",
                            file_path=processed_name,
                            file_size=0,
                            content_type="image/png"
                        )
                        db.add(asset)
                        db.commit()
                        
                        return {
                            "status": "COMPLETED",
                            "task_id": task_id,
                            "original_object": object_name,
                            "processed_url": processed_url
                        }
                    else:
                        error_msg = res.get("error", "Task failed on Colab")
                        if db_task:
                            db_task.status = "FAILED"
                            db_task.error = error_msg
                        db.commit()
                        
                        redis_client.publish("task_updates", json.dumps({
                            "task_id": task_id,
                            "status": "FAILED",
                            "progress": 0,
                            "error": error_msg
                        }))
                        raise Exception(error_msg)
                finally:
                    db.close()
            time.sleep(0.5)
            
        # Timeout
        db = SessionLocal()
        try:
            db_task = db.query(Task).filter(Task.task_id == task_id).first()
            if db_task:
                db_task.status = "FAILED"
                db_task.error = "Execution timed out waiting for Colab worker response"
            db.commit()
        finally:
            db.close()
            
        redis_client.publish("task_updates", json.dumps({
            "task_id": task_id,
            "status": "FAILED",
            "progress": 0,
            "error": "Colab execution timed out"
        }))
        raise TimeoutError("Colab execution timed out")
        
    # Local fallback processing
    from PIL import Image
    from app.scratchpad import scratchpad
    
    temp_in = scratchpad.get_temp_path(suffix="_in.png")
    temp_out = scratchpad.get_temp_path(suffix="_out.png")
    
    db = SessionLocal()
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        db_task = Task(task_id=task_id, name="upscale", status="PROCESSING", progress=0)
        db.add(db_task)
        db.commit()
    db.close()
    
    from app.storage import s3_client
    try:
        # Download S3 object locally
        s3_client.download_file(settings.MINIO_BUCKET_NAME, object_name, str(temp_in))
        
        # Open source image
        img = Image.open(str(temp_in))
        
        # Crop for preview mode if needed
        if params.get("preview", False):
            w, h = img.size
            cw, ch = min(252, w), min(252, h)
            left = (w - cw) // 2
            top = (h - ch) // 2
            img = img.crop((left, top, left + cw, top + ch))
            
        # Progress callback setup
        def progress_callback(percent, msg):
            self.update_state(state="PROGRESS", meta={"percent": percent, "status": msg})
            db = SessionLocal()
            try:
                db_t = db.query(Task).filter(Task.task_id == task_id).first()
                if db_t:
                    db_t.progress = percent
                db.commit()
            finally:
                db.close()
                
            redis_client.publish("task_updates", json.dumps({
                "task_id": task_id,
                "status": "PROCESSING",
                "progress": percent,
                "error": None
            }))
            
        # Resolve tile size
        width, height = img.size
        tile_size = calculate_tile_size(width, height, 16.0)
        
        # Execute upscaler engine with OOM protection
        while True:
            try:
                upscaler = TileUpscaler(tile_size=tile_size, overlap=0.25)
                # We scale by 2.0x default
                upscaled_img = upscaler.upscale(
                    img,
                    upscale_factor=2.0,
                    progress_callback=progress_callback,
                    **params
                )
                break
            except Exception as e:
                is_oom = "out of memory" in str(e).lower() or "oom" in str(e).lower()
                if is_oom and tile_size > 256:
                    logger.warning(f"OOM error: reducing tile size from {tile_size} to {tile_size - 256} and retrying")
                    tile_size = max(256, tile_size - 256)
                else:
                    raise e
                    
        # Save output image
        upscaled_img.save(str(temp_out))
        
        # Upload scale result back
        processed_name = f"processed/scaled_{int(time.time())}_{object_name.split('/')[-1]}"
        with open(str(temp_out), "rb") as f:
            upload_success = upload_object(f.read(), processed_name, content_type="image/png")
            
        # Final success update
        db = SessionLocal()
        try:
            db_t = db.query(Task).filter(Task.task_id == task_id).first()
            if db_t:
                db_t.status = "COMPLETED"
                db_t.progress = 100
            db.commit()
            
            # Create MediaAsset record
            asset = MediaAsset(
                title=f"Upscaled: {object_name.split('/')[-1]}",
                file_path=processed_name,
                file_size=os.path.getsize(str(temp_out)),
                content_type="image/png"
            )
            db.add(asset)
            db.commit()
        finally:
            db.close()
            
        redis_client.publish("task_updates", json.dumps({
            "task_id": task_id,
            "status": "COMPLETED",
            "progress": 100,
            "error": None
        }))
        
        return {
            "status": "COMPLETED",
            "task_id": task_id,
            "original_object": object_name,
            "processed_url": generate_url(processed_name) if upload_success else None
        }
    except Exception as e:
        logger.error(f"Error executing upscale task {task_id}: {e}")
        db = SessionLocal()
        try:
            db_t = db.query(Task).filter(Task.task_id == task_id).first()
            if db_t:
                db_t.status = "FAILED"
                db_t.error = str(e)
            db.commit()
        finally:
            db.close()
            
        redis_client.publish("task_updates", json.dumps({
            "task_id": task_id,
            "status": "FAILED",
            "progress": 0,
            "error": str(e)
        }))
        raise e
    finally:
        scratchpad.remove_path(temp_in)
        scratchpad.remove_path(temp_out)


class CLIPEmbedder:
    _model = None
    _processor = None
    
    @classmethod
    def get_model_and_processor(cls):
        if cls._model is None or cls._processor is None:
            import torch
            from transformers import CLIPModel, CLIPProcessor
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Loading CLIP model onto {device}...")
            cls._model = CLIPModel.from_pretrained('openai/clip-vit-base-patch32').to(device)
            cls._processor = CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32')
        return cls._model, cls._processor

    @classmethod
    def embed_text(cls, text: str) -> list[float]:
        import torch
        model, processor = cls.get_model_and_processor()
        device = next(model.parameters()).device
        inputs = processor(text=[text], return_tensors='pt', padding=True, truncation=True)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model.get_text_features(**inputs)
            feats = outputs.pooler_output
            feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
            emb = feats[0].tolist()
        return cls.pad_embedding(emb)

    @classmethod
    def embed_image(cls, image_bytes: bytes) -> list[float]:
        import torch
        from PIL import Image
        import io
        model, processor = cls.get_model_and_processor()
        device = next(model.parameters()).device
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = processor(images=img, return_tensors='pt')
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model.get_image_features(**inputs)
            feats = outputs.pooler_output
            feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
            emb = feats[0].tolist()
        return cls.pad_embedding(emb)

    @classmethod
    def pad_embedding(cls, emb: list[float], target_dim: int = 1536) -> list[float]:
        if len(emb) < target_dim:
            emb = emb + [0.0] * (target_dim - len(emb))
        return emb[:target_dim]


@celery.task(bind=True, name="app.tasks.generate_media_embedding")
def generate_media_embedding(self, asset_id: int):
    logger.info(f"Generating embedding for MediaAsset id: {asset_id}")
    db = SessionLocal()
    try:
        asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
        if not asset:
            logger.error(f"MediaAsset {asset_id} not found")
            return
        
        is_image = False
        if asset.content_type and asset.content_type.startswith("image/"):
            is_image = True
        
        if is_image:
            try:
                from app.storage import s3_client
                response = s3_client.get_object(Bucket=settings.MINIO_BUCKET_NAME, Key=asset.file_path)
                file_bytes = response['Body'].read()
                embedding = CLIPEmbedder.embed_image(file_bytes)
            except Exception as e:
                logger.error(f"Failed to generate image embedding for {asset.file_path}: {e}. Falling back to text embedding of title.")
                is_image = False
        
        if not is_image:
            clean_title = asset.title
            if '.' in clean_title:
                clean_title = clean_title.rsplit('.', 1)[0]
            clean_title = clean_title.replace('_', ' ').replace('-', ' ').strip()
            embedding = CLIPEmbedder.embed_text(clean_title)
        
        asset.embedding = embedding
        db.commit()
        logger.info(f"Successfully stored embedding for MediaAsset {asset_id}")
    except Exception as e:
        logger.error(f"Error generating embedding for asset {asset_id}: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    print("Starting manual backfill of missing embeddings...")
    db = SessionLocal()
    try:
        assets = db.query(MediaAsset).filter(MediaAsset.embedding == None).all()
        print(f"Found {len(assets)} media assets with missing embeddings.")
        for asset in assets:
            print(f"Processing asset {asset.id}: {asset.title} ({asset.content_type})...")
            try:
                is_image = False
                if asset.content_type and asset.content_type.startswith("image/"):
                    is_image = True
                
                if is_image:
                    try:
                        from app.storage import s3_client
                        response = s3_client.get_object(Bucket=settings.MINIO_BUCKET_NAME, Key=asset.file_path)
                        file_bytes = response['Body'].read()
                        embedding = CLIPEmbedder.embed_image(file_bytes)
                    except Exception as e:
                        print(f"failed image embedding for {asset.file_path}: {e}, falling back to title text")
                        is_image = False
                
                if not is_image:
                    clean_title = asset.title
                    if '.' in clean_title:
                        clean_title = clean_title.rsplit('.', 1)[0]
                    clean_title = clean_title.replace('_', ' ').replace('-', ' ').strip()
                    embedding = CLIPEmbedder.embed_text(clean_title)
                
                asset.embedding = embedding
                db.commit()
                print(f"Generated embedding for asset {asset.id}.")
            except Exception as inner_e:
                print(f"Error processing asset {asset.id}: {inner_e}")
                db.rollback()
        print("Backfill complete.")
    finally:
        db.close()
