"""Application settings, the encrypted secret store and the Colab tunnel."""

import logging
import redis
import json
import asyncio
import time
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Configuration, Task
from app.config import settings
from app.schemas import (
    SecretDeleteOut,
    SecretsIn,
    SecretsMutationOut,
    SecretsStatusOut,
    SecretStatus,
)
from app.services import secrets as secret_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


@router.get("/api/settings")
def get_settings(db: Session = Depends(get_db)):
    """Return all non-secret configuration key/value pairs.

    Rows whose key begins with ``secret.`` hold Fernet ciphertext and are
    filtered out here — returning them would dump encrypted provider API keys
    to every caller.
    """
    configs = db.query(Configuration).all()
    return {
        cfg.key: cfg.value
        for cfg in configs
        if not secret_store.is_secret_key(cfg.key)
    }


@router.post("/api/settings")
def save_settings(data: dict, db: Session = Depends(get_db)):
    for k, v in data.items():
        if secret_store.is_secret_key(k):
            raise HTTPException(
                status_code=400,
                detail="Secret keys must be written via POST /api/settings/secrets",
            )
        cfg = db.query(Configuration).filter(Configuration.key == k).first()
        if cfg:
            cfg.value = str(v)
        else:
            cfg = Configuration(key=k, value=str(v))
            db.add(cfg)
    db.commit()
    return {"status": "SUCCESS", "message": "Settings saved successfully."}


# --- ENCRYPTED PROVIDER SECRETS ---


@router.post("/api/settings/secrets", response_model=SecretsMutationOut)
def save_secrets(payload: SecretsIn, db: Session = Depends(get_db)):
    """Accept plaintext provider keys once and store them Fernet-encrypted.

    Omitted or empty fields leave the existing stored value untouched, so the
    client never has to resubmit a key it cannot read back.
    """
    submitted = {
        "gemini": payload.gemini_api_key,
        "elevenlabs": payload.elevenlabs_api_key,
    }

    updated = []
    for provider, value in submitted.items():
        if value is None:
            continue
        value = value.strip()
        if not value:
            continue
        secret_store.set_secret(provider, value, db=db)
        updated.append(provider)

    if not updated:
        raise HTTPException(status_code=400, detail="No API key values supplied")

    return SecretsMutationOut(status="SUCCESS", updated=updated)


@router.get("/api/settings/secrets", response_model=SecretsStatusOut)
def get_secrets_status(db: Session = Depends(get_db)):
    """Report only whether each provider key is configured, plus its last 4 chars."""
    return SecretsStatusOut(
        gemini=SecretStatus(**secret_store.secret_status("gemini", db=db)),
        elevenlabs=SecretStatus(**secret_store.secret_status("elevenlabs", db=db)),
    )


@router.delete("/api/settings/secrets/{provider}", response_model=SecretDeleteOut)
def remove_secret(provider: str, db: Session = Depends(get_db)):
    """Delete a stored provider key."""
    if provider not in secret_store.PROVIDER_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    deleted = secret_store.delete_secret(provider, db=db)
    return SecretDeleteOut(status="SUCCESS", provider=provider, deleted=deleted)


# --- GOOGLE COLAB TUNNEL CONTROLLER ---


@router.post("/api/colab/tunnel")
def configure_colab(
    url: str = Query(...),
    status: str = Query("running"),
    db: Session = Depends(get_db),
):
    cfg_url = db.query(Configuration).filter(Configuration.key == "colab_tunnel_url").first()
    if cfg_url:
        cfg_url.value = url
    else:
        db.add(Configuration(key="colab_tunnel_url", value=url))

    cfg_status = (
        db.query(Configuration).filter(Configuration.key == "colab_tunnel_status").first()
    )
    if cfg_status:
        cfg_status.value = status
    else:
        db.add(Configuration(key="colab_tunnel_status", value=status))

    db.commit()
    return {"status": "SUCCESS", "colab_url": url, "colab_status": status}


# Redis client for Colab communication broker
redis_client = redis.from_url(settings.REDIS_URL)

class ColabTaskUpdate(BaseModel):
    task_id: str
    status: str
    progress: int
    output: dict = None
    error: str = None

class ColabMetrics(BaseModel):
    vram_used: float
    vram_total: float
    ram_used: float
    ram_total: float
    cpu_load: float
    active_task: str = None

@router.websocket("/api/ws/colab")
async def websocket_colab_endpoint(websocket: WebSocket, token: str = Query(None), db: Session = Depends(get_db)):
    # Validate authorization token
    if token != settings.FUSIONCLIP_SECRET_KEY:
        await websocket.close(code=4003) # Forbidden
        logger.warning("Unauthenticated Colab connection attempt rejected")
        return

    await websocket.accept()
    logger.info("Colab WebSocket bridge connection established")

    # Set tunnel status in DB and notify Redis
    cfg_status = db.query(Configuration).filter(Configuration.key == "colab_tunnel_status").first()
    if cfg_status:
        cfg_status.value = "running"
    else:
        db.add(Configuration(key="colab_tunnel_status", value="running"))
    db.commit()
    
    redis_client.set("colab:connected", "true")

    # Background task to poll Redis for task dispatches and relay to client WebSocket
    async def redis_listener():
        pubsub = redis_client.pubsub()
        pubsub.subscribe("colab_dispatches")
        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    data = message.get("data")
                    if data:
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        await websocket.send_text(data)
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in Redis listener: {e}")
        finally:
            pubsub.unsubscribe("colab_dispatches")
            pubsub.close()

    listener_task = asyncio.create_task(redis_listener())

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            msg_type = payload.get("type")

            if msg_type == "metrics":
                vram_used = payload.get("vram_used", 0)
                vram_total = payload.get("vram_total", 0)
                ram_used = payload.get("ram_used", 0)
                ram_total = payload.get("ram_total", 0)
                
                metrics = {
                    "vram_used": vram_used,
                    "vram_total": vram_total,
                    "ram_used": ram_used,
                    "ram_total": ram_total,
                    "cpu_load": payload.get("cpu_load", 0),
                    "active_task": payload.get("active_task"),
                    "vram_percent": (vram_used / vram_total * 100) if vram_total > 0 else 0,
                    "ram_percent": (ram_used / ram_total * 100) if ram_total > 0 else 0,
                    "updated_at": time.time()
                }
                redis_client.set("colab:metrics", json.dumps(metrics))
                
            elif msg_type == "task_progress":
                task_id = payload.get("task_id")
                percent = payload.get("percent", 0)
                
                db_task = db.query(Task).filter(Task.task_id == task_id).first()
                if db_task:
                    db_task.status = "PROCESSING"
                    db_task.progress = percent
                    db.commit()

                update_payload = {
                    "task_id": task_id,
                    "status": "PROCESSING",
                    "progress": percent,
                    "error": None
                }
                redis_client.publish("task_updates", json.dumps(update_payload))
                
            elif msg_type == "task_complete":
                task_id = payload.get("task_id")
                output = payload.get("output", {})

                db_task = db.query(Task).filter(Task.task_id == task_id).first()
                if db_task:
                    db_task.status = "COMPLETED"
                    db_task.progress = 100
                    db.commit()

                redis_client.set(f"colab_task_result:{task_id}", json.dumps({"status": "SUCCESS", "output": output}))
                
                update_payload = {
                    "task_id": task_id,
                    "status": "COMPLETED",
                    "progress": 100,
                    "error": None
                }
                redis_client.publish("task_updates", json.dumps(update_payload))

            elif msg_type == "task_failed":
                task_id = payload.get("task_id")
                error_msg = payload.get("error", "Unknown error")

                db_task = db.query(Task).filter(Task.task_id == task_id).first()
                if db_task:
                    db_task.status = "FAILED"
                    db_task.error = error_msg
                    db.commit()

                redis_client.set(f"colab_task_result:{task_id}", json.dumps({"status": "FAILURE", "error": error_msg}))

                update_payload = {
                    "task_id": task_id,
                    "status": "FAILED",
                    "progress": 0,
                    "error": error_msg
                }
                redis_client.publish("task_updates", json.dumps(update_payload))

    except WebSocketDisconnect:
        logger.info("Colab WebSocket bridge disconnected")
    except Exception as e:
        logger.error(f"WebSocket error in Colab: {e}")
    finally:
        listener_task.cancel()
        cfg_status = db.query(Configuration).filter(Configuration.key == "colab_tunnel_status").first()
        if cfg_status:
            cfg_status.value = "disconnected"
            db.commit()
        redis_client.set("colab:connected", "false")

@router.get("/api/colab/tasks/pending")
def colab_get_pending_tasks(token: str = Query(None)):
    if token != settings.FUSIONCLIP_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    task_data = redis_client.lpop("colab_pending_tasks_http")
    if task_data:
        if isinstance(task_data, bytes):
            task_data = task_data.decode("utf-8")
        return json.loads(task_data)
    return {"task": None}

@router.post("/api/colab/tasks/update")
def colab_update_task_http(payload: ColabTaskUpdate, token: str = Query(None), db: Session = Depends(get_db)):
    if token != settings.FUSIONCLIP_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    db_task = db.query(Task).filter(Task.task_id == payload.task_id).first()
    if db_task:
        db_task.status = payload.status
        db_task.progress = payload.progress
        if payload.error:
            db_task.error = payload.error
        db.commit()
    
    if payload.status == "COMPLETED":
        redis_client.set(f"colab_task_result:{payload.task_id}", json.dumps({"status": "SUCCESS", "output": payload.output or {}}))
    elif payload.status == "FAILED":
        redis_client.set(f"colab_task_result:{payload.task_id}", json.dumps({"status": "FAILURE", "error": payload.error or "Unknown error"}))

    update_payload = {
        "task_id": payload.task_id,
        "status": payload.status,
        "progress": payload.progress,
        "error": payload.error
    }
    redis_client.publish("task_updates", json.dumps(update_payload))
    return {"status": "SUCCESS"}

@router.post("/api/colab/metrics")
def colab_update_metrics_http(payload: ColabMetrics, token: str = Query(None), db: Session = Depends(get_db)):
    if token != settings.FUSIONCLIP_SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    metrics = {
        "vram_used": payload.vram_used,
        "vram_total": payload.vram_total,
        "ram_used": payload.ram_used,
        "ram_total": payload.ram_total,
        "cpu_load": payload.cpu_load,
        "active_task": payload.active_task,
        "vram_percent": (payload.vram_used / payload.vram_total * 100) if payload.vram_total > 0 else 0,
        "ram_percent": (payload.ram_used / payload.ram_total * 100) if payload.ram_total > 0 else 0,
        "updated_at": time.time()
    }
    redis_client.set("colab:metrics", json.dumps(metrics))
    
    cfg_status = db.query(Configuration).filter(Configuration.key == "colab_tunnel_status").first()
    if cfg_status:
        cfg_status.value = "running"
    else:
        db.add(Configuration(key="colab_tunnel_status", value="running"))
    db.commit()
        
    redis_client.set("colab:connected", "true")
    return {"status": "SUCCESS"}

@router.get("/api/colab/metrics")
def colab_get_metrics():
    data = redis_client.get("colab:metrics")
    if data:
        metrics = json.loads(data)
        if time.time() - metrics.get("updated_at", 0) > 10:
            return {"status": "disconnected", "metrics": None}
        return {"status": "connected", "metrics": metrics}
    return {"status": "disconnected", "metrics": None}
