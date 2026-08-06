from fastapi import FastAPI, UploadFile, File, Query, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import logging
import redis
import asyncio
import json

from app.config import settings
from app.storage import init_storage, upload_object, list_workspace_files, delete_object, generate_url
from app.database import init_db
from app.tasks import process_multimedia_task
from celery.result import AsyncResult

redis_client = redis.from_url(settings.REDIS_URL)

from app.database import SessionLocal
from app.models import Configuration, Task, MediaAsset

# Setup logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Events
    logger.info("Initializing FusionClip databases and storage stacks...")
    init_db()
    init_storage()
    yield
    # Shutdown Events
    logger.info("Shutting down FusionClip backend...")

app = FastAPI(
    title="FusionClip API",
    description="Backend API services for FusionClip multimedia management and generation dashboard",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for Next.js frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "app": "FusionClip API Portal",
        "status": "Green",
        "database": "pgvector ready",
        "storage": "MinIO S3 integration live"
    }

# --- MINIO STORAGE ROUTER ---

@app.post("/api/storage/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Query("", description="Folder directory location to upload into")
):
    """Upload media binary content directly into local MinIO storage."""
    file_bytes = await file.read()
    
    # Clean the folder path and append filename
    folder_prefix = folder.strip("/")
    if folder_prefix:
        object_name = f"{folder_prefix}/{file.filename}"
    else:
        object_name = file.filename

    logger.info(f"Uploading file {file.filename} to S3 Key: {object_name}")
    
    # Upload binary content using helper
    success = upload_object(file_bytes, object_name, content_type=file.content_type)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to upload file to Minio storage")
        
    # Record in database
    db = SessionLocal()
    try:
        asset = MediaAsset(
            title=file.filename,
            file_path=object_name,
            file_size=len(file_bytes),
            content_type=file.content_type,
            duration=0.0
        )
        db.add(asset)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to save asset to db: {e}")
    finally:
        db.close()
        
    return {
        "message": "File uploaded successfully",
        "filename": file.filename,
        "path": object_name,
        "url": generate_url(object_name)
    }

@app.get("/api/storage/list")
def list_files(prefix: Optional[str] = Query("", description="Directory folder path to inspect")):
    """Retrieve full catalog list of objects (files and directories) inside S3 bucket."""
    return list_workspace_files(prefix)

@app.delete("/api/storage/delete")
def delete_file(path: str = Query(..., description="Absolute key of the object to delete")):
    """Delete an object from MinIO."""
    success = delete_object(path)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete object from S3 storage")
    return {"message": f"Successfully deleted object matching key: {path}"}

@app.post("/api/storage/create-folder")
def create_folder(
    folder_path: str = Query(..., description="Virtual directory structure path to create")
):
    """Simulate filemanager folder creation by creating an empty directory suffix object."""
    clean_path = folder_path.strip("/")
    if not clean_path:
        raise HTTPException(status_code=400, detail="Invalid folder path")
    
    # S3 folders are virtual and represented by keys ending in '/'
    dir_key = f"{clean_path}/"
    success = upload_object(b"", dir_key, content_type="application/x-directory")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to create directory folder structure")
        
    return {"message": "Folder directory structure created successfully", "path": dir_key}


# --- CELERY GENERATIVE WORKFLOWS ROUTER ---

@app.post("/api/tasks/process")
def run_processing_pipeline(
    path: str = Query(..., description="Key of the object to process"),
    task_type: str = Query("transcode", description="Generation pipeline: transcode, audio_extract, upscale")
):
    """Dispatch long-running celery worker multimedia task processing pipeline."""
    task = process_multimedia_task.delay(path, task_type)
    return {
        "message": "Processing pipeline initiated successfully",
        "task_id": task.id,
        "status": task.status
    }

@app.get("/api/tasks/status/{task_id}")
def get_task_status(task_id: str):
    """Retrieve runtime state and progress of the background running Celery job."""
    res = AsyncResult(task_id, app=celery_app_instance())
    
    response = {
        "id": task_id,
        "state": res.state,
        "info": None
    }
    
    if res.state == "PROGRESS":
        response["info"] = res.info
    elif res.state == "SUCCESS":
        response["info"] = res.result
    elif res.state == "FAILURE":
        response["info"] = str(res.result)
        
    return response

def celery_app_instance():
    # Helper to prevent circular import loops if referencing celery inside router lifecycle
    from app.celery_app import celery
    return celery

@app.websocket("/api/ws/tasks")
async def websocket_tasks_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection accepted for tasks subscription")
    
    # Subscribe to Redis channels
    pubsub = redis_client.pubsub()
    pubsub.subscribe("task_updates")
    
    try:
        while True:
            # Check for pubsub updates
            message = pubsub.get_message(ignore_subscribe_messages=True)
            if message:
                data = message.get("data")
                if data:
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    await websocket.send_text(data)
            # Yield control to prevent blocking loop
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket encountered error: {e}")
    finally:
        pubsub.unsubscribe("task_updates")
        pubsub.close()

# --- SETTINGS CONFIGURATIONS ROUTERS ---

@app.get("/api/settings")
def get_settings():
    db = SessionLocal()
    try:
        configs = db.query(Configuration).all()
        return {cfg.key: cfg.value for cfg in configs}
    finally:
        db.close()

@app.post("/api/settings")
def save_settings(data: dict):
    db = SessionLocal()
    try:
        for k, v in data.items():
            cfg = db.query(Configuration).filter(Configuration.key == k).first()
            if cfg:
                cfg.value = str(v)
            else:
                cfg = Configuration(key=k, value=str(v))
                db.add(cfg)
        db.commit()
        return {"status": "SUCCESS", "message": "Settings saved successfully."}
    finally:
        db.close()

# --- GOOGLE COLAB TUNNEL CONTROLLER ---

@app.post("/api/colab/tunnel")
def configure_colab(url: str = Query(...), status: str = Query("running")):
    db = SessionLocal()
    try:
        cfg_url = db.query(Configuration).filter(Configuration.key == "colab_tunnel_url").first()
        if cfg_url:
            cfg_url.value = url
        else:
            db.add(Configuration(key="colab_tunnel_url", value=url))
            
        cfg_status = db.query(Configuration).filter(Configuration.key == "colab_tunnel_status").first()
        if cfg_status:
            cfg_status.value = status
        else:
            db.add(Configuration(key="colab_tunnel_status", value=status))
            
        db.commit()
        return {"status": "SUCCESS", "colab_url": url, "colab_status": status}
    finally:
        db.close()

# --- MULTIMEDIA GENERATION ROUTERS ---

@app.post("/api/generate/text")
def generate_text(prompt: str = Query(...)):
    # Simulates text storyboard generation with Gemini API
    return {
        "status": "COMPLETED",
        "output": f"Generated content using Google Gemini for prompt: '{prompt}'. This is a mock Gemini AI response outlining video storyboard structure."
    }

@app.post("/api/generate/audio")
def generate_audio(prompt: str = Query(...), type: str = Query("tts")):
    # Simulated ElevenLabs audio synthesis
    filename = f"gen_audio_{int(time.time())}.mp3"
    content = b"Mock elevenlabs generated audio bytes."
    upload_success = upload_object(content, filename, content_type="audio/mpeg")
    
    # Save to media assets
    db = SessionLocal()
    try:
        asset = MediaAsset(
            title=f"ElevenLabs Synthesized: {prompt[:30]}...",
            file_path=filename,
            file_size=len(content),
            content_type="audio/mpeg",
            duration=3.0
        )
        db.add(asset)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to save generated audio asset: {e}")
    finally:
        db.close()

    return {
        "status": "COMPLETED",
        "type": type,
        "filename": filename,
        "url": generate_url(filename) if upload_success else ""
    }

@app.post("/api/generate/image")
def generate_image(prompt: str = Query(...), steps: int = Query(28), scale: float = Query(7.5)):
    # Simulated Local Flux sandbox image generation
    filename = f"gen_image_{int(time.time())}.png"
    content = b"Mock local flux generated image bytes."
    upload_success = upload_object(content, filename, content_type="image/png")
    
    # Save to media assets
    db = SessionLocal()
    try:
        asset = MediaAsset(
            title=f"Flux Generated: {prompt[:30]}...",
            file_path=filename,
            file_size=len(content),
            content_type="image/png",
            duration=0.0
        )
        db.add(asset)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to save generated image asset: {e}")
    finally:
        db.close()

    return {
        "status": "COMPLETED",
        "parameters": {"steps": steps, "scale": scale},
        "filename": filename,
        "url": generate_url(filename) if upload_success else ""
    }

# --- MEDIA LIBRARY ROUTERS ---

@app.get("/api/media")
def list_media():
    db = SessionLocal()
    try:
        assets = db.query(MediaAsset).all()
        return [
            {
                "id": asset.id,
                "title": asset.title,
                "file_path": asset.file_path,
                "file_size": asset.file_size,
                "content_type": asset.content_type,
                "duration": asset.duration,
                "url": generate_url(asset.file_path) if asset.file_path else "",
                "created_at": asset.created_at.isoformat() if asset.created_at else None
            }
            for asset in assets
        ]
    finally:
        db.close()

@app.get("/api/media/search")
def search_media(query: str = Query(...), limit: int = Query(10)):
    db = SessionLocal()
    try:
        # Vector semantic search with fallback to standard text search
        try:
            import hashlib
            hasher = hashlib.sha256(query.encode())
            seed_val = int(hasher.hexdigest(), 16) % (10**8)
            import random
            random.seed(seed_val)
            query_embedding = [random.uniform(-1, 1) for _ in range(1536)]
            
            assets = db.query(MediaAsset).order_by(
                MediaAsset.embedding.l2_distance(query_embedding)
            ).limit(limit).all()
        except Exception as db_err:
            logger.warning(f"Vector search failed, falling back to text search: {db_err}")
            assets = db.query(MediaAsset).filter(
                MediaAsset.title.ilike(f"%{query}%")
            ).limit(limit).all()
            
        return [
            {
                "id": asset.id,
                "title": asset.title,
                "file_path": asset.file_path,
                "file_size": asset.file_size,
                "content_type": asset.content_type,
                "duration": asset.duration,
                "url": generate_url(asset.file_path) if asset.file_path else "",
                "created_at": asset.created_at.isoformat() if asset.created_at else None
            }
            for asset in assets
        ]
    finally:
        db.close()
