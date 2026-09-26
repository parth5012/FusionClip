"""Local PyTorch Model Scaffold (#99).

Provides:
- Model registry (PINNED_ROSTER, ModelMetadata, ModelRegistry, model_registry)
- VRAM Guard (VRAMGuard, vram_guard, VRAMRefusalError, NoGPUError, InsufficientVRAMError)
- Contracts (DegradedResponse, DegradedReason, FallbackTier, make_degraded_response)
"""

from app.ml.contracts import (
    DegradedReason,
    DegradedResponse,
    FallbackTier,
    make_degraded_response,
)
from app.ml.guard import (
    InsufficientVRAMError,
    NoGPUError,
    VRAMGuard,
    VRAMRefusalError,
    vram_guard,
)
from app.ml.registry import (
    INFERENCE_LOCK,
    PINNED_ROSTER,
    ModelMetadata,
    ModelRegistry,
    model_registry,
)
from app.ml.image import (
    ASPECT_RATIO_DIMENSIONS,
    SUPPORTED_SCHEDULERS,
    run_local_image_generation,
)
from app.ml.audio import (
    SUPPORTED_AUDIO_TYPES,
    build_audio_filename,
    make_audio_loader,
    run_local_audio_generation,
)
from app.ml.skin_enhancer import (
    DEFAULT_FLEXIBLE_PRESET,
    DEFAULT_SKIN_DETAIL,
    FLEXIBLE_PRESETS,
    MAX_INPUT_DIMENSION,
    MODE_ENGINES,
    SKIN_MODES,
    SLIDER_MAX,
    SLIDER_MIN,
    apply_skin_post_filters,
    apply_texture_retention,
    build_skin_filename,
    describe_skin_surface,
    get_flexible_preset,
    make_diffbir_loader,
    make_gfpgan_loader,
    map_skin_detail_to_guidance,
    map_skin_detail_to_texture_retention,
    map_sharpen_to_percent,
    map_smart_grain_to_sigma,
    run_skin_enhancement,
)

__all__ = [
    "DegradedReason",
    "DegradedResponse",
    "FallbackTier",
    "make_degraded_response",
    "InsufficientVRAMError",
    "NoGPUError",
    "VRAMGuard",
    "VRAMRefusalError",
    "vram_guard",
    "PINNED_ROSTER",
    "ModelMetadata",
    "ModelRegistry",
    "model_registry",
    "INFERENCE_LOCK",
    "SUPPORTED_SCHEDULERS",
    "ASPECT_RATIO_DIMENSIONS",
    "run_local_image_generation",
    "SUPPORTED_AUDIO_TYPES",
    "build_audio_filename",
    "make_audio_loader",
    "run_local_audio_generation",
    "SKIN_MODES",
    "MODE_ENGINES",
    "FLEXIBLE_PRESETS",
    "DEFAULT_FLEXIBLE_PRESET",
    "DEFAULT_SKIN_DETAIL",
    "SLIDER_MIN",
    "SLIDER_MAX",
    "MAX_INPUT_DIMENSION",
    "get_flexible_preset",
    "map_skin_detail_to_guidance",
    "map_skin_detail_to_texture_retention",
    "map_sharpen_to_percent",
    "map_smart_grain_to_sigma",
    "apply_skin_post_filters",
    "apply_texture_retention",
    "make_gfpgan_loader",
    "make_diffbir_loader",
    "build_skin_filename",
    "run_skin_enhancement",
    "describe_skin_surface",
]
