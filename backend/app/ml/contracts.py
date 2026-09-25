"""Typed contracts for local inference, VRAM guard decisions, and degraded fallbacks (#99).

Implements Decision #3 from grilling ticket #98:
Labeled honest fallback tier (`degraded: true` + machine-readable `reason`).
Surfaced to the UI whenever VRAM guard refuses or no GPU is present.
"""

from enum import Enum
import re
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator

# Matches the legacy placeholder payloads the map exists to eliminate, e.g.
# "Mock local flux generated image bytes." / "Mock elevenlabs generated audio bytes."
_MOCK_BYTES_RE = re.compile(r"mock\b.*\bbytes\b", re.IGNORECASE)


class DegradedReason(str, Enum):
    """Machine-readable refusal or degradation reasons."""

    NO_GPU = "no_gpu"
    INSUFFICIENT_VRAM = "insufficient_vram"
    MODEL_NOT_FOUND = "model_not_found"
    LOAD_FAILED = "load_failed"
    DEVICE_OFFLINE = "device_offline"


class FallbackTier(str, Enum):
    """Fallback strategies available when local ML cannot execute."""

    CLOUD_API = "cloud_api"
    DOWNGRADE_MODEL = "downgrade_model"
    CPU_FALLBACK = "cpu_fallback"
    REFUSAL = "refusal"


class DegradedResponse(BaseModel):
    """Explicitly marked degraded / fallback response contract.

    Surfaced to the UI whenever local GPU inference cannot fit or GPU is absent.
    Implements Decision #3: labeled honest fallback tier (degraded: true + machine-readable reason).
    """

    degraded: bool = True
    reason: str = Field(
        ...,
        description="Machine-readable refusal reason, e.g. 'no_gpu' or 'insufficient_vram'",
    )
    message: str = Field(
        ...,
        description="Human-readable explanation of why inference was degraded or refused",
    )
    model_id: Optional[str] = Field(
        default=None, description="Requested model id"
    )
    vram_required_gb: Optional[float] = Field(
        default=None, description="VRAM required in GB (model + overhead)"
    )
    vram_available_gb: Optional[float] = Field(
        default=None, description="Free VRAM available in GB"
    )
    fallback_tier: Optional[str] = Field(
        default=FallbackTier.REFUSAL.value, description="Active fallback tier"
    )
    details: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional context or diagnostics"
    )

    @field_validator("message")
    @classmethod
    def _forbid_mock_byte_payloads(cls, v: str) -> str:
        """Decision #3: the degraded path must never reintroduce 'Mock ... bytes'.

        Enforced at runtime rather than only by a test, so no caller (or future
        caller) can smuggle the old placeholder strings through this contract.
        """
        if _MOCK_BYTES_RE.search(v):
            raise ValueError(
                "Mock byte-string payloads are forbidden by decision #3; "
                "return an explicit degraded reason instead"
            )
        return v


def make_degraded_response(
    reason: str,
    message: str,
    model_id: Optional[str] = None,
    vram_required_gb: Optional[float] = None,
    vram_available_gb: Optional[float] = None,
    fallback_tier: str = FallbackTier.REFUSAL.value,
    details: Optional[Dict[str, Any]] = None,
) -> DegradedResponse:
    """Helper to construct a standardized DegradedResponse."""
    return DegradedResponse(
        degraded=True,
        reason=reason,
        message=message,
        model_id=model_id,
        vram_required_gb=vram_required_gb,
        vram_available_gb=vram_available_gb,
        fallback_tier=fallback_tier,
        details=details or {},
    )
