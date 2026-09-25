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
    PINNED_ROSTER,
    ModelMetadata,
    ModelRegistry,
    model_registry,
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
]
