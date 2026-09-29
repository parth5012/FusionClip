"""Image Editor API router (#121, map #75).

Versioned edit-recipe JSON is the source of truth (#118): the client preview
is CSS-only, and POST /api/editor/render is the v1 authoritative re-render
(synchronous PIL in `app.ml.image_adjust`; a Celery/ffmpeg async variant is
the noted gap, and `recipe_to_ffmpeg_filter` is the mapping it would consume).

Validation lives here rather than in pydantic so an out-of-range slider is a
400 with an actionable message instead of a 422 — the same rule
`app/routers/skin_enhance.py` follows (#111 decision 4: never a silent clamp).
The recipe body is therefore `Dict[str, Any]`, validated by
`image_adjust.normalize_recipe`, which also refuses unknown keys.
"""

import logging
import math
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db
from app.ml.image_adjust import (
    describe_editor_surface,
    list_editor_recipes,
    normalize_recipe,
    run_editor_render,
    save_editor_recipe,
)
from app.routers.generate import SAFE_REFERENCE_PATTERN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/editor", tags=["editor"])


class EditorRecipeBody(BaseModel):
    """Save/render request: a source key plus a (possibly partial) recipe."""

    source_path: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Catalog file_path of the source image to edit",
    )
    recipe: Dict[str, Any] = Field(
        default_factory=dict,
        description="Partial or full edit recipe; missing ops fill defaults",
    )


MAX_SOURCE_PATH_LENGTH = 256


def _validate_safe_source_path(value: str) -> str:
    """Refuse a `source_path` that is not a relative catalog key.

    Same rules as the skin endpoint's image_path (shared
    `SAFE_REFERENCE_PATTERN` plus spaces, because uploads keep the user's
    original filename as the object key): `..`, a leading `/`, backslashes
    and over-length keys are refused with 400.
    """
    if (
        not value
        or not value.strip()
        or ".." in value
        or value.startswith("/")
        or "\\" in value
        or len(value) > MAX_SOURCE_PATH_LENGTH
        or not SAFE_REFERENCE_PATTERN.match(value.replace(" ", ""))
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid source_path {value!r}: must be a non-empty relative catalog "
                "file_path (subfolders allowed) with no '..', no leading '/', no "
                "backslashes and no other special characters."
            ),
        )
    return value


def _validate_recipe_dict(recipe: Any) -> Dict[str, Any]:
    """Normalize the recipe now so a malformed body is 400, never 422.

    `normalize_recipe` raises HTTPException(400) itself; this wrapper only
    guards the non-dict JSON shapes it does not cover.
    """
    if recipe is None:
        return normalize_recipe({})
    if not isinstance(recipe, dict):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid recipe {recipe!r}: must be a JSON object of op names to integers.",
        )
    for key, value in recipe.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Slider '{key}' value {value} must be a finite whole number."
                ),
            )
    return normalize_recipe(recipe)


@router.get("/presets")
def get_editor_presets():
    """Recipe schema version, slider ranges, rotate range and crop aspects."""
    return describe_editor_surface()


@router.post("/recipe")
def save_recipe(
    payload: EditorRecipeBody,
    db: Session = Depends(get_db),
):
    """Persist one versioned edit-recipe JSON sidecar for a source image.

    Missing recipe keys fill defaults; the response echoes the full recipe
    plus its new monotonic version. The source must exist in storage.
    """
    source_path = _validate_safe_source_path(payload.source_path.strip())
    recipe = _validate_recipe_dict(payload.recipe)
    logger.info(f"Editor recipe save requested for '{source_path}': {recipe}")
    return save_editor_recipe(source_path, recipe, db)


@router.get("/recipes")
def get_recipes(
    source_path: str = Query(..., min_length=1, max_length=256),
    db: Session = Depends(get_db),
):
    """All persisted recipe versions for a source, oldest first (reload leg)."""
    _validate_safe_source_path(source_path.strip())
    _ = db  # listing reads sidecars from storage; db is accepted for symmetry.
    return list_editor_recipes(source_path.strip())


@router.post("/render")
def render_recipe(
    payload: EditorRecipeBody,
    db: Session = Depends(get_db),
):
    """Re-render the source through the recipe and persist the derivative.

    Synchronous by design in v1 (Pillow runs everywhere, including CPU-only
    CI): the response is the result — `edited/<stem>_edit_<token>.png` with a
    `MediaAsset.source_path` lineage row plus the co-saved recipe sidecar —
    so edit-save-reload fidelity is assertable without a GPU or a broker.
    """
    source_path = _validate_safe_source_path(payload.source_path.strip())
    recipe = _validate_recipe_dict(payload.recipe)
    logger.info(f"Editor render requested for '{source_path}': {recipe}")
    return run_editor_render(source_path, recipe, db)
