"""Non-destructive Adjust engine for the Image Editor core (#121, map #75).

Source of truth is a versioned edit-recipe JSON (#118 decision: hybrid wins —
recipe JSON as source of truth, client WebGL/Konva preview, Celery/ffmpeg as
the authoritative render). This module is the v1 authoritative render: a
synchronous, dependency-free (Pillow + stdlib only) executor applying the 7
Adjust ops plus rotate/crop-aspect, so it runs on any host including CPU-only
CI. The async Celery + ffmpeg path (`eq`/`curves`/seeded-noise, see
`recipe_to_ffmpeg_filter`) is the noted gap, not a second implementation.

Composition order is fixed and documented: center-crop to aspect -> rotate ->
tone (exposure/brightness, contrast, highlights, shadows, tint) -> grain last.
Every stage whose parameters are all-default is *skipped*, so the default
recipe is a pixel-exact identity rather than an accumulation of rounding
error ("0 means off", same rule as the skin post-filters).

Grain is deterministic: the RNG is seeded by the stable fingerprint of the
canonical recipe, so re-rendering the same recipe yields byte-identical PNGs
(edit-save-reload fidelity). PNG encoding itself carries no timestamps.

Heavy imports: none. PIL is already a hard backend dependency.
"""

import hashlib
import io
import json
import logging
import math
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from PIL import Image, ImageChops, ImageEnhance
from sqlalchemy.orm import Session

from app.models import MediaAsset
from app.services.embedding import get_embedding
from app.storage import (
    download_object,
    generate_url,
    list_workspace_files,
    upload_object,
)

logger = logging.getLogger(__name__)

#: Recipe schema version. Bumped only on a breaking recipe-shape change.
RECIPE_VERSION = 1

#: The 7 Adjust ops (#119 v1 scope) in canonical order.
ADJUST_OPS = (
    "exposure",
    "brightness",
    "contrast",
    "highlights",
    "shadows",
    "tint",
    "grain",
)

#: Per-op slider ranges. Grain starts at 0 (there is no negative grain).
SLIDER_RANGES: Dict[str, Dict[str, int]] = {
    "exposure": {"min": -100, "max": 100, "default": 0},
    "brightness": {"min": -100, "max": 100, "default": 0},
    "contrast": {"min": -100, "max": 100, "default": 0},
    "highlights": {"min": -100, "max": 100, "default": 0},
    "shadows": {"min": -100, "max": 100, "default": 0},
    "tint": {"min": -100, "max": 100, "default": 0},
    "grain": {"min": 0, "max": 100, "default": 0},
}

ROTATE_MIN, ROTATE_MAX, ROTATE_DEFAULT = -45, 45, 0
CROP_ASPECTS = ("free", "1:1", "4:3", "16:9")
DEFAULT_CROP_ASPECT = "free"

DEFAULT_RECIPE: Dict[str, Any] = {
    **{op: 0 for op in ADJUST_OPS},
    "rotate": ROTATE_DEFAULT,
    "crop_aspect": DEFAULT_CROP_ASPECT,
}

#: Longest side cap. The grain stage builds one full-frame noise buffer, so an
#: unbounded panorama would balloon time and memory on a shared worker. 4096
#: keeps a 3:2 frame under 11M pixels; inputs above it are downscaled once,
#: before any tone op, and the response reports the rendered size.
MAX_LONGEST_SIDE = 4096

EDIT_PREFIX = "edited"
RECIPE_PREFIX = "edits"

VIDEO_CONTENT_PREFIXES = ("video/",)
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".mkv", ".avi"})


# ---------------------------------------------------------------------------
# Recipe validation + canonical form
# ---------------------------------------------------------------------------


def _validate_int_slider(name: str, value: Any) -> int:
    """Range- and integrality-check one slider, mirroring the skin 400 text.

    #111 decision 4 (adopted by #121): out-of-range is 400, never a silent
    clamp, and the wire format is an integer range, so 12.5 is refused rather
    than truncated. Non-finite is checked first: `int(nan)` raises ValueError
    and `int(inf)` raises OverflowError, neither of which is a range error.
    """
    spec = SLIDER_RANGES[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider '{name}' value {value!r} must be a whole number: the wire "
                f"format is an integer {spec['min']}..{spec['max']} range."
            ),
        )
    if not math.isfinite(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider '{name}' value {value} must be a finite whole number: the "
                f"wire format is an integer {spec['min']}..{spec['max']} range."
            ),
        )
    if value != int(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider '{name}' value {value} must be a whole number: the wire "
                f"format is an integer {spec['min']}..{spec['max']} range."
            ),
        )
    as_int = int(value)
    if as_int < spec["min"] or as_int > spec["max"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider '{name}' value {as_int} is out of range: must be between "
                f"{spec['min']} and {spec['max']}. Values are not clamped."
            ),
        )
    return as_int


def normalize_recipe(raw: Any) -> Dict[str, Any]:
    """Validate a caller-supplied recipe dict and return the full recipe.

    Missing keys fill defaults (a partial recipe is a valid edit); unknown
    keys are refused so a typo'd op name cannot silently do nothing.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid recipe {raw!r}: must be a JSON object of op names to integers.",
        )
    known = set(ADJUST_OPS) | {"rotate", "crop_aspect"}
    unknown = sorted(k for k in raw if k not in known)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown recipe key(s) {unknown}: expected only "
                f"{sorted(known)}. Unknown keys are refused, never ignored."
            ),
        )
    recipe: Dict[str, Any] = dict(DEFAULT_RECIPE)
    for op in ADJUST_OPS:
        if op in raw:
            recipe[op] = _validate_int_slider(op, raw[op])
    if "rotate" in raw:
        recipe["rotate"] = _validate_rotate(raw["rotate"])
    if "crop_aspect" in raw:
        aspect = raw["crop_aspect"]
        if aspect not in CROP_ASPECTS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid crop_aspect {aspect!r}: must be one of "
                    f"{list(CROP_ASPECTS)}."
                ),
            )
        recipe["crop_aspect"] = aspect
    return recipe


def _validate_rotate(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider 'rotate' value {value!r} must be a whole number: the wire "
                f"format is an integer {ROTATE_MIN}..{ROTATE_MAX} range."
            ),
        )
    if not math.isfinite(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider 'rotate' value {value} must be a finite whole number: the "
                f"wire format is an integer {ROTATE_MIN}..{ROTATE_MAX} range."
            ),
        )
    if value != int(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider 'rotate' value {value} must be a whole number: the wire "
                f"format is an integer {ROTATE_MIN}..{ROTATE_MAX} range."
            ),
        )
    as_int = int(value)
    if as_int < ROTATE_MIN or as_int > ROTATE_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider 'rotate' value {as_int} is out of range: must be between "
                f"{ROTATE_MIN} and {ROTATE_MAX}. Values are not clamped."
            ),
        )
    return as_int


def canonical_recipe_json(recipe: Dict[str, Any]) -> str:
    """Stable serialization: sorted keys, no whitespace variance."""
    return json.dumps(recipe, sort_keys=True, separators=(",", ":"))


def recipe_fingerprint(recipe: Dict[str, Any]) -> int:
    """Stable 64-bit fingerprint of the canonical recipe (grain seed)."""
    digest = hashlib.sha256(canonical_recipe_json(recipe).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def recipe_to_ffmpeg_filter(recipe: Dict[str, Any]) -> str:
    """Forward-compatible ffmpeg mapping for a future Celery worker.

    NOT executed by the v1 synchronous path (which runs the PIL pipeline
    below so CI and CPU-only hosts render identically). Kept next to the PIL
    factors so the two cannot drift: exposure/brightness share one brightness
    term, contrast one contrast term, shadows ride saturation, tint rides hue,
    grain rides `noise`. Seeded determinism lives in the v1 RNG seed, not in
    the filter string (the `noise` filter takes no seed).
    """
    full = normalize_recipe(recipe)
    brightness = (full["exposure"] + full["brightness"]) / 200.0
    contrast = 1 + full["contrast"] / 150.0
    saturation = 1 + full["shadows"] / 300.0
    parts = [
        f"eq=brightness={brightness:.4f}:contrast={contrast:.4f}"
        f":saturation={saturation:.4f}"
    ]
    if full["tint"]:
        parts.append(f"hue=h={full['tint'] / 4:.1f}")
    if full["grain"]:
        parts.append(f"noise=alls={int(full['grain'] / 100 * 25)}:allf=t")
    return ",".join(parts)


def describe_editor_surface() -> Dict[str, Any]:
    """The endpoint's own description of its inputs (GET /api/editor/presets)."""
    return {
        "version": RECIPE_VERSION,
        "sliders": {op: dict(spec) for op, spec in SLIDER_RANGES.items()},
        "rotate": {"min": ROTATE_MIN, "max": ROTATE_MAX, "default": ROTATE_DEFAULT},
        "crop_aspects": list(CROP_ASPECTS),
        "default_crop": DEFAULT_CROP_ASPECT,
        "composition_order": ["crop", "rotate", "tone", "grain"],
        "authoritative": "synchronous PIL (v1); Celery/ffmpeg async is a noted gap",
    }


# ---------------------------------------------------------------------------
# Source resolution (storage only — never the server filesystem)
# ---------------------------------------------------------------------------


def _load_source_image(source_path: str, db: Optional[Session]) -> Image.Image:
    """Resolve, video-check and decode the source image.

    Same rules as the skin loader: the catalog content_type is authoritative
    when the asset is known, the extension is the fallback, and bytes come
    from storage and nowhere else (no local-filesystem fallback, so a
    storage key can never become an arbitrary file reader).
    """
    content_type: Optional[str] = None
    if db is not None:
        try:
            asset = (
                db.query(MediaAsset).filter(MediaAsset.file_path == source_path).first()
            )
            if asset is not None:
                content_type = asset.content_type
        except Exception as exc:  # a catalog hiccup must not mask the real error
            logger.warning(f"Image editor: catalog lookup for '{source_path}' failed: {exc}")
            db.rollback()

    extension = Path(source_path).suffix.lower()
    is_video = (content_type or "").lower().startswith(VIDEO_CONTENT_PREFIXES) or (
        extension in VIDEO_EXTENSIONS
    )
    if is_video:
        raise HTTPException(
            status_code=400,
            detail=(
                "video_input_not_supported: Image editing is images only in v1. "
                f"Refused '{source_path}' as a video."
            ),
        )

    raw = download_object(source_path)
    if raw is None:
        raise HTTPException(
            status_code=400,
            detail=f"source_not_found: Source image '{source_path}' was not found in storage.",
        )
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image.convert("RGB")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"source_unreadable: Source image '{source_path}' is unreadable or corrupt: {exc}",
        )


def _cap_longest_side(image: Image.Image) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_LONGEST_SIDE:
        return image
    scale = MAX_LONGEST_SIDE / longest
    target = (int(width * scale), int(height * scale))
    logger.info(f"Image editor: capping {width}x{height} input to {target[0]}x{target[1]}")
    return image.resize(target, resample=Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------
# The adjust pipeline (crop -> rotate -> tone -> grain)
# ---------------------------------------------------------------------------


def _apply_crop(image: Image.Image, aspect: str) -> Image.Image:
    if aspect == "free":
        return image
    across, down = (int(p) for p in aspect.split(":"))
    width, height = image.size
    target = across / down
    current = width / height
    if abs(current - target) < 1e-9:
        return image
    if current > target:
        new_width = int(height * target)
        left = (width - new_width) // 2
        return image.crop((left, 0, left + new_width, height))
    new_height = int(width / target)
    top = (height - new_height) // 2
    return image.crop((0, top, width, top + new_height))


def _luminance_mask(image: Image.Image, high: bool) -> Image.Image:
    """Soft 0..255 mask selecting highlights (high=True) or shadows."""
    gray = image.convert("L")
    if high:
        lut = [min(255, max(0, value - 128) * 2) for value in range(256)]
    else:
        lut = [min(255, max(0, 128 - value) * 2) for value in range(256)]
    return gray.point(lut)


def _apply_tone(image: Image.Image, recipe: Dict[str, Any]) -> Image.Image:
    out = image
    lift = 1 + (recipe["exposure"] + recipe["brightness"]) / 200.0
    if lift != 1.0:
        out = ImageEnhance.Brightness(out).enhance(lift)
    contrast = 1 + recipe["contrast"] / 150.0
    if contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if recipe["highlights"]:
        factor = 1 + recipe["highlights"] / 200.0
        adjusted = ImageEnhance.Brightness(out).enhance(factor)
        out = Image.composite(adjusted, out, _luminance_mask(out, high=True))
    if recipe["shadows"]:
        factor = 1 + recipe["shadows"] / 200.0
        adjusted = ImageEnhance.Brightness(out).enhance(factor)
        out = Image.composite(adjusted, out, _luminance_mask(out, high=False))
    if recipe["tint"]:
        red_scale = 1 + recipe["tint"] / 300.0
        blue_scale = 1 - recipe["tint"] / 300.0
        red_lut = [min(255, max(0, int(v * red_scale))) for v in range(256)]
        blue_lut = [min(255, max(0, int(v * blue_scale))) for v in range(256)]
        red, green, blue = out.split()
        out = Image.merge("RGB", (red.point(red_lut), green, blue.point(blue_lut)))
    return out


def _apply_grain(image: Image.Image, amount: int, seed: int) -> Image.Image:
    """Seeded film grain. amount 0 is skipped by the caller (0 means off)."""
    rng = random.Random(seed)
    width, height = image.size
    noise = Image.frombytes("L", (width, height), rng.randbytes(width * height))
    strength = amount / 100.0 * 0.6
    pos_lut = [min(255, int(max(0.0, (v - 128)) * strength)) for v in range(256)]
    neg_lut = [min(255, int(max(0.0, (128 - v)) * strength)) for v in range(256)]
    pos = noise.point(pos_lut).convert("RGB")
    neg = noise.point(neg_lut).convert("RGB")
    return ImageChops.subtract(ImageChops.add(image, pos), neg)


def apply_recipe(image: Image.Image, recipe: Dict[str, Any]) -> Image.Image:
    """Run the fixed composition order over an already-decoded image."""
    full = normalize_recipe(recipe)
    out = _apply_crop(image, full["crop_aspect"])
    if full["rotate"]:
        # PIL rotates counter-clockwise; the UI/CSS convention is clockwise.
        out = out.rotate(-full["rotate"], resample=Image.Resampling.BICUBIC, expand=True)
    out = _apply_tone(out, full)
    if full["grain"]:
        out = _apply_grain(out, full["grain"], recipe_fingerprint(full))
    return out


# ---------------------------------------------------------------------------
# Filenames, recipe sidecars, versions
# ---------------------------------------------------------------------------


_UNSAFE_STEM_CHARS = __import__("re").compile(r"[^A-Za-z0-9._-]+")


def _sanitize_stem(source_path: str) -> str:
    stem = _UNSAFE_STEM_CHARS.sub("_", Path(source_path).stem).strip("._")
    return stem or "edited"


def _existing_recipe_versions(source_path: str) -> List[int]:
    """Version numbers already stored for this source's stem (0 if none)."""
    stem = _sanitize_stem(source_path)
    prefix = f"{RECIPE_PREFIX}/"
    try:
        listing = list_workspace_files(prefix)
    except Exception as exc:
        logger.warning(f"Image editor: recipe listing failed: {exc}")
        return []
    versions: List[int] = []
    marker = f"{stem}_recipe_v"
    for entry in (listing or {}).get("files", []):
        name = entry.get("name", "")
        if not name.startswith(marker):
            continue
        tail = name[len(marker):]
        number = tail.split("_", 1)[0].split(".", 1)[0]
        if number.isdigit():
            versions.append(int(number))
    return versions


def _next_recipe_version(source_path: str) -> int:
    existing = _existing_recipe_versions(source_path)
    return (max(existing) + 1) if existing else 1


def _recipe_sidecar_key(source_path: str, version: int) -> str:
    token = uuid.uuid4().hex[:12]
    return f"{RECIPE_PREFIX}/{_sanitize_stem(source_path)}_recipe_v{version}_{token}.json"


def _render_output_key(source_path: str) -> str:
    token = uuid.uuid4().hex[:12]
    return f"{EDIT_PREFIX}/{_sanitize_stem(source_path)}_edit_{token}.png"


def _sidecar_document(
    source_path: str, recipe: Dict[str, Any], version: int
) -> Dict[str, Any]:
    return {
        "version": version,
        "recipe_version": RECIPE_VERSION,
        "source_path": source_path,
        "recipe": recipe,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def save_editor_recipe(
    source_path: str, recipe_raw: Any, db: Optional[Session] = None
) -> dict:
    """Validate + persist one versioned edit-recipe JSON sidecar.

    The source must exist in storage (a recipe for a missing image is a
    dangling version, refused as `source_not_found`), and video is refused by
    the same rule as render. Returns the SAVED envelope with the new version.
    """
    recipe = normalize_recipe(recipe_raw)
    # Existence + video gate without decoding (decode happens at render time,
    # not save time): a recipe for a missing image would be a dangling version.
    _assert_source_usable(source_path, db)

    version = _next_recipe_version(source_path)
    key = _recipe_sidecar_key(source_path, version)
    document = _sidecar_document(source_path, recipe, version)
    payload = json.dumps(document, sort_keys=True, indent=1).encode("utf-8")
    if not upload_object(payload, key, content_type="application/json"):
        raise HTTPException(
            status_code=500,
            detail="storage_write_failed: Could not persist the edit recipe to storage.",
        )
    return {
        "status": "SAVED",
        "version": version,
        "recipe_version": RECIPE_VERSION,
        "source_path": source_path,
        "file_path": key,
        "url": generate_url(key),
        "recipe": recipe,
    }


def _assert_source_usable(source_path: str, db: Optional[Session]) -> None:
    """Video + existence gate shared by save (no decode) and render."""
    content_type: Optional[str] = None
    if db is not None:
        try:
            asset = (
                db.query(MediaAsset).filter(MediaAsset.file_path == source_path).first()
            )
            if asset is not None:
                content_type = asset.content_type
        except Exception as exc:
            logger.warning(f"Image editor: catalog lookup for '{source_path}' failed: {exc}")
            db.rollback()
    extension = Path(source_path).suffix.lower()
    is_video = (content_type or "").lower().startswith(VIDEO_CONTENT_PREFIXES) or (
        extension in VIDEO_EXTENSIONS
    )
    if is_video:
        raise HTTPException(
            status_code=400,
            detail=(
                "video_input_not_supported: Image editing is images only in v1. "
                f"Refused '{source_path}' as a video."
            ),
        )
    if download_object(source_path) is None:
        raise HTTPException(
            status_code=400,
            detail=f"source_not_found: Source image '{source_path}' was not found in storage.",
        )


def list_editor_recipes(source_path: str) -> dict:
    """All persisted recipe versions for a source, oldest first."""
    stem = _sanitize_stem(source_path)
    prefix = f"{RECIPE_PREFIX}/"
    try:
        listing = list_workspace_files(prefix)
    except Exception as exc:
        logger.warning(f"Image editor: recipe listing failed: {exc}")
        listing = {"files": []}
    versions = []
    marker = f"{stem}_recipe_v"
    for entry in (listing or {}).get("files", []):
        name = entry.get("name", "")
        path = entry.get("path", f"{prefix}{name}")
        if not name.startswith(marker):
            continue
        raw = download_object(path)
        if raw is None:
            continue
        try:
            document = json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        if document.get("source_path") != source_path:
            continue
        versions.append(
            {
                "version": document.get("version"),
                "recipe_version": document.get("recipe_version", 1),
                "file_path": path,
                "url": entry.get("url") or generate_url(path),
                "recipe": document.get("recipe", {}),
                "created_at": document.get("created_at"),
            }
        )
    versions.sort(key=lambda v: (v["version"] is None, v["version"]))
    return {"source_path": source_path, "versions": versions}


def run_editor_render(
    source_path: str, recipe_raw: Any, db: Optional[Session] = None
) -> dict:
    """Re-render the source through the recipe and persist the derivative.

    Steps: validate -> resolve/decode/cap source -> apply pipeline ->
    PNG-encode -> upload `edited/<stem>_edit_<token>.png` + co-save the recipe
    sidecar -> persist a MediaAsset with `source_path` lineage (the before/
    after UI pairs on this, no new UI needed) -> COMPLETED envelope.
    """
    recipe = normalize_recipe(recipe_raw)
    image = _load_source_image(source_path, db)
    image = _cap_longest_side(image)
    finished = apply_recipe(image, recipe)

    out_buf = io.BytesIO()
    finished.save(out_buf, format="PNG", optimize=True)
    png_bytes = out_buf.getvalue()

    filename = _render_output_key(source_path)
    if not upload_object(png_bytes, filename, content_type="image/png"):
        raise HTTPException(
            status_code=500,
            detail="storage_write_failed: Could not upload the edited image to storage.",
        )

    # Co-save the exact recipe this render used: the PNG is the artifact, the
    # sidecar is the source of truth that re-creates it.
    version = _next_recipe_version(source_path)
    recipe_key = _recipe_sidecar_key(source_path, version)
    sidecar = json.dumps(
        _sidecar_document(source_path, recipe, version), sort_keys=True, indent=1
    ).encode("utf-8")
    if not upload_object(sidecar, recipe_key, content_type="application/json"):
        logger.error(f"Image editor: rendered '{filename}' but recipe sidecar failed")
        raise HTTPException(
            status_code=500,
            detail="storage_write_failed: Rendered the image but could not persist its edit recipe.",
        )

    if db is not None:
        try:
            title = f"Edited: {Path(source_path).stem}"
            asset = MediaAsset(
                title=title,
                file_path=filename,
                file_size=len(png_bytes),
                content_type="image/png",
                duration=0.0,
                # Lineage: before/after pairs on this, no new UI needed.
                source_path=source_path,
                embedding=get_embedding(title),
            )
            db.add(asset)
            db.commit()
        except Exception as exc:
            logger.error(f"Image editor: failed to save edited asset: {exc}")
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"catalog_write_failed: Failed to save the edited asset: {exc}",
            )

    return {
        "status": "COMPLETED",
        "recipe_version": RECIPE_VERSION,
        "source_path": source_path,
        "filename": filename,
        "url": generate_url(filename),
        "recipe_path": recipe_key,
        "recipe_url": generate_url(recipe_key),
        "version": version,
        "image_size": list(finished.size),
        "parameters": recipe,
        "ffmpeg_filter": recipe_to_ffmpeg_filter(recipe),
    }
