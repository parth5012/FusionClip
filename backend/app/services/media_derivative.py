"""Unified Media Derivative Service.

Deep module encapsulating asset lineage (source_path), atomic object storage uploads,
database catalog records (MediaAsset), stem sanitization, and compensating storage deletions
across all generative pipelines (upscale, skin-enhance, editor, bgremove).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, BinaryIO, Callable, Dict, List, Optional, Tuple, Union
import uuid

from sqlalchemy.orm import Session

from app.models import MediaAsset
from app.services.embedding import get_embedding
from app.storage import delete_object, generate_url, upload_object

logger = logging.getLogger(__name__)

DEFAULT_STEM = "asset"
UNSAFE_STEM_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

PIPELINE_FOLDERS: Dict[str, str] = {
    "upscale": "upscaled",
    "skin_enhance": "skin_enhanced",
    "bgremove": "bg_removed",
    "editor": "edited",
}

PIPELINE_TITLE_PREFIXES: Dict[str, str] = {
    "upscale": "Upscaled",
    "skin_enhance": "Skin Enhanced",
    "bgremove": "Background Removed",
    "editor": "Edited",
}


def sanitize_stem(source_path: str, default: str = DEFAULT_STEM) -> str:
    """Sanitize source path stem to safe alphanumeric characters, dashes, and underscores.

    Strips leading and trailing dots and underscores. Collapses consecutive dots to avoid
    accidental path traversal tokens ('..'). Falls back to default ('asset') if empty.
    """
    raw_stem = Path(source_path).stem
    cleaned = UNSAFE_STEM_CHARS.sub("_", raw_stem).strip("._")
    cleaned = re.sub(r"\.{2,}", "_", cleaned).strip("._")
    return cleaned or default


def _validate_safe_key(key: str) -> None:
    """Ensure key contains no path traversal (..) or leading / backslashes."""
    if not key or ".." in key or key.startswith("/") or "\\" in key:
        raise ValueError(f"Insecure or invalid storage key: '{key}'")


DEFAULT_FALLBACK_STEMS: Dict[str, str] = {
    "upscale": "asset",
    "skin_enhance": "portrait",
    "bgremove": "asset",
    "editor": "edited",
}


def build_derivative_key(
    source_path: str,
    pipeline: str,
    qualifier: Optional[str] = None,
    token: Optional[str] = None,
    extension: str = "png",
    default_stem: Optional[str] = None,
) -> str:
    """Construct standardized derivative key: {folder}/{stem}_{qualifier}_{12hex}.{ext}."""
    folder = PIPELINE_FOLDERS.get(pipeline, pipeline)
    folder = UNSAFE_STEM_CHARS.sub("_", folder.strip()).strip("._")
    d_stem = default_stem or DEFAULT_FALLBACK_STEMS.get(pipeline, DEFAULT_STEM)
    stem = sanitize_stem(source_path, default=d_stem)
    tok = token or uuid.uuid4().hex[:12]
    tok = UNSAFE_STEM_CHARS.sub("_", tok.strip()).strip("._")
    tok = re.sub(r"\.{2,}", "_", tok).strip("._")
    ext = extension.lstrip(".")
    ext = re.sub(r"[^a-zA-Z0-9]", "", ext) or "png"

    if qualifier:
        clean_qualifier = UNSAFE_STEM_CHARS.sub("_", qualifier.strip()).strip("._")
        clean_qualifier = re.sub(r"\.{2,}", "_", clean_qualifier).strip("._")
        if clean_qualifier:
            key = f"{folder}/{stem}_{clean_qualifier}_{tok}.{ext}"
            _validate_safe_key(key)
            return key

    key = f"{folder}/{stem}_{tok}.{ext}"
    _validate_safe_key(key)
    return key


@dataclass
class DerivativeResult:
    """Structured result returned by record_derivative."""

    output_path: str
    url: str
    source_path: str
    file_size: int
    asset: Optional[MediaAsset] = None
    sidecar_paths: Dict[str, str] = field(default_factory=dict)
    uploaded_keys: List[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        """Alias for output_path for compatibility across routers."""
        return self.output_path

    def cleanup(self, delete_fn: Optional[Callable[[str], Any]] = None) -> None:
        """Compensating delete helper for callers managing deferred transactions."""
        deleter = delete_fn or delete_object
        for key in self.uploaded_keys:
            try:
                deleter(key)
            except Exception as del_err:
                logger.warning(f"Failed to delete uploaded key '{key}' during cleanup: {del_err}")


class MediaDerivativeService:
    """Service encapsulating derivative uploads, catalog tracking, and atomic rollback."""

    @staticmethod
    def sanitize_stem(source_path: str, default: str = DEFAULT_STEM) -> str:
        return sanitize_stem(source_path, default=default)

    @staticmethod
    def build_derivative_key(
        source_path: str,
        pipeline: str,
        qualifier: Optional[str] = None,
        token: Optional[str] = None,
        extension: str = "png",
        default_stem: Optional[str] = None,
    ) -> str:
        return build_derivative_key(
            source_path=source_path,
            pipeline=pipeline,
            qualifier=qualifier,
            token=token,
            extension=extension,
            default_stem=default_stem,
        )

    @staticmethod
    def record_derivative(
        db: Optional[Session],
        source_path: str,
        file_data: Union[bytes, BinaryIO],
        pipeline: str,
        qualifier: Optional[str] = None,
        task_token: Optional[str] = None,
        output_path: Optional[str] = None,
        title: Optional[str] = None,
        content_type: str = "image/png",
        duration: Optional[float] = 0.0,
        embedding: Optional[List[float]] = None,
        sidecars: Optional[Dict[str, Union[bytes, Tuple[bytes, str]]]] = None,
        auto_commit: bool = True,
        upload_fn: Optional[Any] = None,
        delete_fn: Optional[Any] = None,
    ) -> DerivativeResult:
        """Atomically upload derivative and auxiliary sidecars, register catalog row, and handle rollbacks."""
        uploader = upload_fn or upload_object
        deleter = delete_fn or delete_object

        if hasattr(file_data, "getvalue"):
            data_bytes = file_data.getvalue()
        elif hasattr(file_data, "read"):
            if hasattr(file_data, "seekable") and file_data.seekable():
                file_data.seek(0)
            data_bytes = file_data.read()
        else:
            data_bytes = bytes(file_data)

        if len(data_bytes) == 0:
            raise ValueError("file_data cannot be empty")

        ext_part = content_type.split(";")[0].split("/")[-1].strip().lower()
        clean_ext = re.sub(r"[^a-zA-Z0-9]", "", ext_part) or "png"

        # Resolve output storage key
        resolved_key = output_path or build_derivative_key(
            source_path=source_path,
            pipeline=pipeline,
            qualifier=qualifier,
            token=task_token,
            extension=clean_ext,
        )
        _validate_safe_key(resolved_key)
        if sidecars:
            for s_key in sidecars:
                _validate_safe_key(s_key)

        uploaded_keys: List[str] = []

        # 1. Upload main derivative
        if not uploader(data_bytes, resolved_key, content_type=content_type):
            raise RuntimeError(f"Failed to upload derivative to {resolved_key}")
        uploaded_keys.append(resolved_key)

        # 2. Upload any auxiliary sidecar files
        sidecar_urls: Dict[str, str] = {}
        if sidecars:
            for s_key, s_val in sidecars.items():
                _validate_safe_key(s_key)
                if isinstance(s_val, tuple):
                    s_bytes, s_ctype = s_val
                else:
                    s_bytes = s_val
                    s_ctype = "application/json" if s_key.endswith(".json") else "application/octet-stream"

                if not uploader(s_bytes, s_key, content_type=s_ctype):
                    logger.error(f"Failed to upload sidecar '{s_key}', triggering compensating delete")
                    for orphan_key in uploaded_keys:
                        try:
                            deleter(orphan_key)
                        except Exception as del_err:
                            logger.warning(
                                f"Failed to delete orphaned key '{orphan_key}' during sidecar abort: {del_err}"
                            )
                    raise RuntimeError(f"Failed to upload sidecar to {s_key}")

                uploaded_keys.append(s_key)
                sidecar_urls[s_key] = generate_url(s_key)

        # 3. Compute title and embedding
        stem = sanitize_stem(source_path)
        if not title:
            prefix = PIPELINE_TITLE_PREFIXES.get(pipeline, pipeline.capitalize())
            qualifier_str = f" ({qualifier})" if qualifier else ""
            title = f"{prefix}: {stem}{qualifier_str}"

        if embedding is None:
            try:
                embedding = get_embedding(title)
            except Exception as emb_err:
                logger.warning(f"Could not compute embedding for derivative title '{title}': {emb_err}")
                embedding = None

        # 4. Insert MediaAsset catalog row if db is provided
        asset: Optional[MediaAsset] = None
        if db is not None:
            committed = False
            try:
                asset = MediaAsset(
                    title=title,
                    file_path=resolved_key,
                    file_size=len(data_bytes),
                    content_type=content_type,
                    duration=duration or 0.0,
                    source_path=source_path,
                    embedding=embedding,
                )
                db.add(asset)
                if auto_commit:
                    db.commit()
                    committed = True
                    try:
                        db.refresh(asset)
                    except Exception as ref_err:
                        logger.warning(f"Could not refresh asset after commit: {ref_err}")
                else:
                    db.flush()
            except Exception as db_exc:
                if not committed:
                    logger.error(f"Failed to commit derivative catalog row for '{resolved_key}': {db_exc}")
                    if auto_commit:
                        try:
                            db.rollback()
                        except Exception as rb_err:
                            logger.warning(f"Error during db.rollback: {rb_err}")

                    # Synchronous compensating delete for all uploaded objects
                    for orphan_key in uploaded_keys:
                        try:
                            deleter(orphan_key)
                        except Exception as del_err:
                            logger.warning(
                                f"Failed to delete orphaned object '{orphan_key}' after catalog commit failure: {del_err}"
                            )
                raise db_exc

        url = generate_url(resolved_key)
        return DerivativeResult(
            asset=asset,
            output_path=resolved_key,
            url=url,
            source_path=source_path,
            file_size=len(data_bytes),
            sidecar_paths=sidecar_urls,
            uploaded_keys=uploaded_keys,
        )


# Module-level convenience functions
record_derivative = MediaDerivativeService.record_derivative
