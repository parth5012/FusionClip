"""Application settings, the encrypted secret store and the Colab tunnel."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Configuration
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
