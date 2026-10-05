"""Skin Enhancer API router (#112).

One endpoint over the face-crop enhancer in `app.ml.skin_enhancer`, plus a
read-only description of the input surface so the panel (ticket #137) renders
modes, presets and slider ranges from the same source of truth the endpoint
validates against.

Validation lives here rather than in the schema so an out-of-range slider is a
**400 with an actionable message**, matching how `app/routers/upscale.py` refuses
out-of-range sliders. FastAPI would otherwise answer 422 from pydantic, and
#111 decision 4 requires 400 and forbids a silent clamp.
"""

import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db
from app.ml.skin_enhancer import (
    DEFAULT_FLEXIBLE_PRESET,
    DEFAULT_MODE,
    DEFAULT_SKIN_DETAIL,
    FLEXIBLE_PRESETS,
    MAX_INPUT_DIMENSION,
    SKIN_MODES,
    SLIDER_MAX,
    SLIDER_MIN,
    describe_skin_surface,
    get_flexible_preset,
    run_skin_enhancement,
)
from app.routers._paths import has_safe_catalog_chars

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skin-enhance", tags=["skin-enhance"])


class SkinEnhanceRequest(BaseModel):
    """Skin-enhance request body.

    The three sliders are declared `float` on purpose: their contract is a 0-100
    *integer* range, and validating that here is what lets an out-of-range or
    fractional value come back as a 400 with a readable message. Declaring them
    `int` would move the check into pydantic and answer 422 instead.
    """

    image_path: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Catalog file_path of the portrait image to enhance",
    )
    mode: str = Field(DEFAULT_MODE, description="faithful, creative, or flexible")
    preset: Optional[str] = Field(
        None,
        description="Flexible-mode preset (Magnific `optimized_for`); ignored-by-design "
        "outside flexible, where it is refused with 400 rather than dropped",
    )
    sharpen: float = Field(0, description="0..100 edge sharpening (all modes)")
    smart_grain: float = Field(0, description="0..100 film grain (all modes)")
    skin_detail: float = Field(
        DEFAULT_SKIN_DETAIL,
        description="0..100; texture retention in faithful, DiffBIR guidance in creative/flexible",
    )


def _validate_slider(name: str, value: float) -> int:
    """Range- and integrality-check a 0..100 slider, returning it as an int.

    #111 decision 4: out-of-range is 400, never a silent clamp, and the wire
    format is an integer range, so 12.5 is refused rather than truncated to 12.

    Non-finite is checked *first* and for its own reason: Python's json parser
    accepts the `NaN` and `Infinity` tokens and parses `1e999` as `inf`, and then
    `int(float('nan'))` raises ValueError while `int(float('inf'))` raises
    OverflowError. Neither is a range error, so letting them reach the integrality
    check turned a caller mistake into a 500.
    """
    if not math.isfinite(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider '{name}' value {value} must be a finite whole number: the "
                f"wire format is an integer {SLIDER_MIN}..{SLIDER_MAX} range."
            ),
        )
    if value != int(value):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider '{name}' value {value} must be a whole number: the wire format "
                f"is an integer {SLIDER_MIN}..{SLIDER_MAX} range."
            ),
        )
    as_int = int(value)
    if as_int < SLIDER_MIN or as_int > SLIDER_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Slider '{name}' value {as_int} is out of range: must be between "
                f"{SLIDER_MIN} and {SLIDER_MAX}. Values are not clamped."
            ),
        )
    return as_int


MAX_IMAGE_PATH_LENGTH = 256


def _is_safe_image_path_chars(value: str) -> bool:
    """Character-class check against the shared catalog-key pattern (spaces allowed)."""
    return has_safe_catalog_chars(value)


def _validate_safe_image_path(value: str) -> str:
    """Refuse an `image_path` that is not a relative catalog key, and return it.

    Deliberately the same rules as `generate._validate_safe_reference`, which
    guards `/api/generate/video`'s `source`: one shared `SAFE_REFERENCE_PATTERN`
    instead of a second regex that can drift from it. That pattern allows `/`,
    and it has to - #111's chosen integration is a per-asset action in
    FileManager, which is a directory browser, so the keys users click are
    `upscaled/...`, `uploads/...`, `processed/...`. The old slash-free pattern
    400'd every one of them. `..`, a leading `/` and a backslash stay refused, and
    the length is re-checked here because pydantic's `max_length` validates the
    raw field, not this stripped value.

    The path is only ever used as a storage key: the enhancer reads source bytes
    from storage and nowhere else, so a key that does not resolve is a
    `source_not_found` 400 rather than a local file read.
    """
    if (
        not value
        or not value.strip()
        or ".." in value
        or value.startswith("/")
        or "\\" in value
        or len(value) > MAX_IMAGE_PATH_LENGTH
        or not _is_safe_image_path_chars(value)
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid image_path {value!r}: must be a non-empty relative catalog "
                "file_path (subfolders allowed) with no '..', no leading '/', no "
                "backslashes and no other special characters."
            ),
        )
    return value


@router.get("/presets")
def get_skin_enhance_presets():
    """Modes, Flexible presets, slider ranges and the input ceiling, in one read."""
    return describe_skin_surface()


@router.post("")
def enhance_skin(
    payload: SkinEnhanceRequest,
    db: Session = Depends(get_db),
):
    """Restore the faces in a portrait and return the derivative asset.

    Success returns `status: COMPLETED` with the output key, its URL, the engine
    that ran, the face count and the resolved parameters. Refusals that are the
    caller's fault (bad mode/preset/slider, a video, an unreadable source, no face
    in frame) are 400 with a machine-readable reason slug. Inability to run at
    all - no GPU, not enough VRAM, a load or inference failure - is *not* a 400:
    it returns the labeled degraded envelope at HTTP 200 exactly as
    `run_local_image_generation` does, so the panel can tell "you asked for
    something impossible" apart from "this host cannot do it right now".
    """
    image_path = _validate_safe_image_path(payload.image_path.strip())

    mode = (payload.mode or DEFAULT_MODE).strip().lower()
    if mode not in SKIN_MODES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported skin-enhance mode '{payload.mode}'. "
                f"Supported modes: {', '.join(SKIN_MODES)}."
            ),
        )

    preset: Optional[str] = None
    if payload.preset is not None and payload.preset.strip():
        preset = payload.preset.strip()
        if mode != "flexible":
            # Magnific's `optimized_for` is a Flexible-only surface. Accepting it
            # here and dropping it would leave the user believing the preset ran.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"preset '{preset}' is only valid in flexible mode, not '{mode}'. "
                    "Omit the parameter, or switch mode to flexible."
                ),
            )
        try:
            get_flexible_preset(preset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    elif mode == "flexible":
        preset = DEFAULT_FLEXIBLE_PRESET

    sharpen = _validate_slider("sharpen", payload.sharpen)
    smart_grain = _validate_slider("smart_grain", payload.smart_grain)
    skin_detail = _validate_slider("skin_detail", payload.skin_detail)

    logger.info(
        f"Skin enhance requested: mode={mode} preset={preset or '-'} "
        f"sharpen={sharpen} smart_grain={smart_grain} skin_detail={skin_detail} "
        f"(ceiling {MAX_INPUT_DIMENSION}px, {len(FLEXIBLE_PRESETS)} presets)"
    )

    return run_skin_enhancement(
        image_path=image_path,
        mode=mode,
        preset=preset,
        sharpen=sharpen,
        smart_grain=smart_grain,
        skin_detail=skin_detail,
        db=db,
    )
