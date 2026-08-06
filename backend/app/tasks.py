import time
import subprocess
import re
import os
import json
import redis
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
    
    # regex to match time=HH:MM:SS.MS in ffmpeg output
    time_regex = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")
    
    db = SessionLocal()
    try:
        # Start subprocess
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            # Scrape time status
            match = time_regex.search(line)
            if match and duration > 0:
                hours, minutes, seconds, ms = map(int, match.groups())
                current_time = hours * 3600 + minutes * 60 + seconds + ms / 100.0
                percent = min(int((current_time / duration) * 100), 99)
                
                # Update Celery
                if celery_task:
                    celery_task.update_state(
                        state="PROGRESS",
                        meta={"percent": percent, "status": f"Processing media: {percent}%"}
                    )
                
                # Publish to Redis Pub/Sub
                update_payload = {
                    "task_id": task_id,
                    "status": "PROCESSING",
                    "progress": percent,
                    "error": None
                }
                redis_client.publish("task_updates", json.dumps(update_payload))
                
                # Update Database
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
        # Update fail state
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

# Fast task endpoint
@celery.task(bind=True, name="app.tasks.process_media_fast")
def process_media_fast(self, object_name: str, task_type: str = "thumbnail"):
    logger.info(f"Processing fast task: {task_type} for {object_name}")
    task_id = self.request.id
    
    db = SessionLocal()
    # Ensure task entry exists in DB
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        db_task = Task(task_id=task_id, name=task_type, status="PROCESSING", progress=0)
        db.add(db_task)
        db.commit()
    db.close()
    
    # Simulate processing or run actual transcoding
    # For now, let's simulate step progress and publish updates
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

    # Upload cleanups/processed URLs
    processed_name = f"processed/thumb_{object_name.split('/')[-1]}"
    simulated_media = b"Simulated thumbnail content bytes."
    upload_success = upload_object(simulated_media, processed_name, content_type="image/jpeg")
    
    return {
        "status": "COMPLETED",
        "task_id": task_id,
        "original_object": object_name,
        "processed_url": generate_url(processed_name) if upload_success else ""
    }

# Heavy task queue endpoint
@celery.task(bind=True, name="app.tasks.process_media_heavy")
def process_media_heavy(self, object_name: str, task_type: str = "transcode"):
    logger.info(f"Processing heavy task: {task_type} for {object_name}")
    task_id = self.request.id
    
    # We simulate download file, process with FFmpeg, upload back
    # Retrieve file from S3 to temporary scratchpad path
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
        # Download S3 object locally
        s3_client.download_file(settings.MINIO_BUCKET_NAME, object_name, str(temp_in))
        
        # Parse duration
        duration = parse_duration(str(temp_in))
        if duration == 0.0:
            duration = 10.0 # fallback
            
        # Run ffmpeg to transcode video
        cmd = ["ffmpeg", "-y", "-i", str(temp_in), "-vcodec", "libx264", "-acodec", "aac", str(temp_out)]
        run_ffmpeg_with_progress(cmd, duration, task_id, celery_task=self)
        
        # Upload output from temp path
        processed_name = f"processed/{object_name.split('/')[-1]}"
        with open(str(temp_out), "rb") as f:
            upload_success = upload_object(f.read(), processed_name, content_type="video/mp4")
            
        # Final success update
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
        db = SessionLocal()
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task:
            db_task.status = "FAILED"
            db_task.error = str(e)
            db.commit()
        db.close()
        
        redis_client.publish("task_updates", json.dumps({
            "task_id": task_id,
            "status": "FAILED",
            "progress": 0,
            "error": str(e)
        }))
        raise e
    finally:
        # Clean scratchpad paths
        scratchpad.remove_path(temp_in)
        scratchpad.remove_path(temp_out)

# For backward compatibility
@celery.task(bind=True)
def process_multimedia_task(self, object_name: str, task_type: str = "transcode"):
    # Forward to fast or heavy queue depending on task type
    if task_type in ["thumbnail", "waveform"]:
        return process_media_fast(object_name, task_type)
    else:
        return process_media_heavy(object_name, task_type)
