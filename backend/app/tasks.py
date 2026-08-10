import time
import subprocess
import re
import os
import json
import redis
from datetime import datetime, timezone
from app.celery_app import celery
from app.storage import upload_object, generate_url
from app.scratchpad import scratchpad
from app.database import SessionLocal
from app.models import Task, MediaAsset
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Cache redis client
redis_client = redis.from_url(settings.REDIS_URL)

# Errors that should trigger auto-retry
TRANSIENT_ERRORS = (
    "OOM",
    "out of memory",
    "MemoryError",
    "TimeoutError",
    "timeout",
    "ConnectionError",
    "connection refused",
    "connection reset",
    "TemporaryFailure",
    "ServiceUnavailable",
    "503",
    "429",
)

# Errors that should NOT be retried
PERMANENT_ERRORS = (
    "invalid file",
    "bad parameters",
    "validation error",
    "not found",
    "404",
    "permission denied",
    "403",
    "unsupported format",
    "corrupt",
)


def is_transient_error(error_msg: str) -> bool:
    """Determine if an error is transient (retryable) or permanent."""
    error_lower = error_msg.lower()
    for pattern in PERMANENT_ERRORS:
        if pattern.lower() in error_lower:
            return False
    for pattern in TRANSIENT_ERRORS:
        if pattern.lower() in error_lower:
            return True
    return False


def exponential_backoff(retry_count: int) -> int:
    """Calculate exponential backoff countdown: 2^retry_count * 60 seconds."""
    return (2 ** retry_count) * 60


def update_task_retry(db_task: Task, retry_count: int, db):
    """Update retry tracking fields on a task."""
    db_task.retry_count = retry_count
    db_task.last_retry_at = datetime.now(timezone.utc)
    db.commit()

def parse_duration(file_path: str) -> float:
    """Get the duration of a media file in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Failed to parse duration for {file_path}: {e}")
        return 0.0


def run_ffmpeg_with_progress(cmd, duration: float, task_id: str, celery_task=None):
    """Run an FFmpeg command in a subprocess and update progress via Redis/Celery/DB."""
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")

    time_regex = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

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

                if celery_task:
                    celery_task.update_state(
                        state="PROGRESS",
                        meta={"percent": percent, "status": f"Processing media: {percent}%"}
                    )

                update_payload = {
                    "task_id": task_id,
                    "status": "PROCESSING",
                    "progress": percent,
                    "error": None
                }
                redis_client.publish("task_updates", json.dumps(update_payload))

                db_task = db.query(Task).filter(Task.task_id == task_id).first()
                if db_task:
                    db_task.status = "PROCESSING"
                    db_task.progress = percent
                    db.commit()

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)

    except Exception as e:
        logger.error(f"FFmpeg process encountered an error: {e}")
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task:
            db_task.status = "FAILED"
            db_task.error = str(e)
            db.commit()

        redis_client.publish("task_updates", json.dumps({
            "task_id": task_id,
            "status": "FAILED",
            "progress": 0,
            "error": str(e)
        }))
        raise e
    finally:
        db.close()


def _handle_task_failure(task_id: str, e: Exception, max_retries: int):
    """Handle task failure with retry logic. Returns True if retry was scheduled."""
    error_msg = str(e)
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
                "max_retries": max_retries
            }))
            return True
        else:
            db_task.status = "FAILED"
            db_task.error = error_msg
            db.commit()

            redis_client.publish("task_updates", json.dumps({
                "task_id": task_id,
                "status": "FAILED",
                "progress": 0,
                "error": error_msg,
                "retry_count": current_retry,
                "max_retries": max_retries
            }))
            return False
    finally:
        db.close()

# Fast task endpoint
@celery.task(bind=True, name="app.tasks.process_media_fast", max_retries=3)
def process_media_fast(self, object_name: str, task_type: str = "thumbnail"):
    logger.info(f"Processing fast task: {task_type} for {object_name}")
    task_id = self.request.id

    db = SessionLocal()
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        db_task = Task(task_id=task_id, name=task_type, status="PROCESSING", progress=0)
        db.add(db_task)
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
        upload_success = upload_object(simulated_media, processed_name, content_type="image/jpeg")

        return {
            "status": "COMPLETED",
            "task_id": task_id,
            "original_object": object_name,
            "processed_url": generate_url(processed_name) if upload_success else ""
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

    is_colab = redis_client.get("colab:connected") == b"true"
    if is_colab:
        logger.info(f"Colab worker detected! Offloading heavy task {task_type} for {object_name}")
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

    return _original_process_media_heavy(self, object_name, task_type)

def _original_process_media_heavy(self, object_name: str, task_type: str = "transcode"):
    logger.info(f"Processing heavy task: {task_type} for {object_name}")
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
            "processed_url": generate_url(processed_name) if upload_success else ""
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


# For backward compatibility
@celery.task(bind=True)
def process_multimedia_task(self, object_name: str, task_type: str = "transcode"):
    if task_type in ["thumbnail", "waveform"]:
        return process_media_fast(object_name, task_type)
    else:
        return process_media_heavy(object_name, task_type)
