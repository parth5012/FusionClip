"""Encrypted server-side store for third-party provider API keys.

Values are Fernet-encrypted with a key derived from ``FUSIONCLIP_SECRET_KEY``
and persisted in the existing ``configurations`` table under keys prefixed
``secret.``. No migration is required: ``Configuration.value`` is already a
``Text`` column and the ciphertext is urlsafe-base64 ASCII.

Plaintext is written once (POST /api/settings/secrets) and never read back over
HTTP — callers only ever receive ``{configured, last4}``. Celery workers, which
have no HTTP request context, resolve keys directly through :func:`get_secret`.
"""

import base64
import hashlib
import logging
from contextlib import contextmanager
from typing import Dict, Iterator, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import DEV_DEFAULT_SECRET_KEY, settings
from app.database import SessionLocal
from app.models import Configuration

logger = logging.getLogger(__name__)

#: Every configuration row whose key starts with this prefix holds ciphertext
#: and must never be exposed by GET /api/settings.
SECRET_KEY_PREFIX = "secret."

#: Public provider name -> configuration key.
PROVIDER_KEYS: Dict[str, str] = {
    "gemini": f"{SECRET_KEY_PREFIX}gemini_api_key",
    "elevenlabs": f"{SECRET_KEY_PREFIX}elevenlabs_api_key",
}


class SecretStoreError(RuntimeError):
    """Raised when a stored secret cannot be decrypted."""


def is_secret_key(key: str) -> bool:
    """True when a configuration key holds encrypted secret material.

    Casefolded (L-1): a variant-cased prefix like `SECRET.x` is still
    recognised as a secret key, removing a footgun before five branches
    add config keys.
    """
    return key.lower().startswith(SECRET_KEY_PREFIX)


def _fernet() -> Fernet:
    """Build a Fernet instance from the configured master key.

    ``FUSIONCLIP_SECRET_KEY`` is an arbitrary passphrase, so it is run through
    PBKDF2-HMAC-SHA256 (600k iters, fixed app salt) to derive exactly 32 bytes,
    then urlsafe-base64 encoded to satisfy Fernet's key format. A bare SHA-256
    (the previous KDF) is fast to brute-force when the master key is a human
    passphrase; PBKDF2 raises the cost materially (M-2).
    """
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        settings.FUSIONCLIP_SECRET_KEY.encode("utf-8"),
        b"fusionclip-secret-store-v1",
        600_000,
    )
    return Fernet(base64.urlsafe_b64encode(digest))


def warn_if_dev_secret_key() -> bool:
    """Log a loud warning when the dev-default master key is still in use.

    Refuses to start (M-4) when the dev-default key is paired with a
    non-localhost CORS origin — that combination "encrypts" secrets under a
    published key while reachable from the network, which is obfuscation, not
    encryption. Localhost-only dev is allowed to proceed with a warning.
    """
    if settings.FUSIONCLIP_SECRET_KEY == DEV_DEFAULT_SECRET_KEY:
        origins = settings.CORS_ORIGINS_LIST
        non_localhost = [
            o for o in origins
            if "localhost" not in o and "127.0.0.1" not in o
        ]
        if non_localhost:
            raise RuntimeError(
                "FUSIONCLIP_SECRET_KEY is the insecure development default and "
                f"CORS_ORIGINS includes non-localhost origins {non_localhost}. "
                "Stored provider API keys would be effectively unprotected and "
                "reachable from the network. Set FUSIONCLIP_SECRET_KEY to a strong "
                "unique value before deploying."
            )
        logger.warning(
            "FUSIONCLIP_SECRET_KEY is the insecure development default. "
            "Stored provider API keys are effectively unprotected. "
            "Set FUSIONCLIP_SECRET_KEY to a strong unique value before deploying."
        )
        return True
    return False


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext secret into a storable ASCII token."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(token: str) -> str:
    """Decrypt a stored token back to plaintext."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretStoreError(
            "Stored secret could not be decrypted; FUSIONCLIP_SECRET_KEY may have changed."
        ) from exc


@contextmanager
def _session(db: Optional[Session]) -> Iterator[Session]:
    """Use the caller's session, or open (and close) a short-lived one."""
    if db is not None:
        yield db
        return
    owned = SessionLocal()
    try:
        yield owned
    finally:
        owned.close()


def resolve_key(provider_or_key: str) -> str:
    """Map a provider alias ('gemini') to its full configuration key."""
    if provider_or_key in PROVIDER_KEYS:
        return PROVIDER_KEYS[provider_or_key]
    if is_secret_key(provider_or_key):
        return provider_or_key
    return f"{SECRET_KEY_PREFIX}{provider_or_key}"


def set_secret(provider_or_key: str, plaintext: str, db: Optional[Session] = None) -> None:
    """Encrypt and persist a secret, replacing any existing value."""
    if not plaintext:
        raise ValueError("Refusing to store an empty secret value")

    key = resolve_key(provider_or_key)
    token = encrypt_value(plaintext)

    with _session(db) as session:
        cfg = session.query(Configuration).filter(Configuration.key == key).first()
        if cfg:
            cfg.value = token
        else:
            session.add(Configuration(key=key, value=token))
        session.commit()


def get_secret(provider_or_key: str, db: Optional[Session] = None) -> Optional[str]:
    """Return the decrypted secret, or None when it has never been configured."""
    key = resolve_key(provider_or_key)
    with _session(db) as session:
        cfg = session.query(Configuration).filter(Configuration.key == key).first()
        if not cfg or not cfg.value:
            return None
        return decrypt_value(cfg.value)


def has_secret(provider_or_key: str, db: Optional[Session] = None) -> bool:
    """True when a secret is stored and decryptable."""
    key = resolve_key(provider_or_key)
    with _session(db) as session:
        cfg = session.query(Configuration).filter(Configuration.key == key).first()
        if not cfg or not cfg.value:
            return False
        # Read the value out before the session may be closed.
        token = cfg.value

    try:
        decrypt_value(token)
    except SecretStoreError:
        logger.error("Secret '%s' is present but undecryptable.", key)
        return False
    return True


def delete_secret(provider_or_key: str, db: Optional[Session] = None) -> bool:
    """Remove a stored secret. Returns True when a row was actually deleted."""
    key = resolve_key(provider_or_key)
    with _session(db) as session:
        cfg = session.query(Configuration).filter(Configuration.key == key).first()
        if not cfg:
            return False
        session.delete(cfg)
        session.commit()
        return True


def secret_status(provider_or_key: str, db: Optional[Session] = None) -> Dict[str, Optional[str]]:
    """Redacted status for a provider: ``{configured, last4}`` only."""
    key = resolve_key(provider_or_key)
    with _session(db) as session:
        cfg = session.query(Configuration).filter(Configuration.key == key).first()
        if not cfg or not cfg.value:
            return {"configured": False, "last4": None}
        token = cfg.value

    try:
        plaintext = decrypt_value(token)
    except SecretStoreError:
        logger.error("Secret '%s' is present but undecryptable.", key)
        return {"configured": False, "last4": None}

    return {"configured": True, "last4": plaintext[-4:] if len(plaintext) >= 4 else None}
