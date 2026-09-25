"""VRAM Guard for GPU inference job admission and refusal (#99).

Provides clean, typed errors that can be translated to API / degraded responses.
Distinctly detects "no GPU at all" vs "insufficient VRAM".
Implements auto-downgrade model selection for Decision #4.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.ml.contracts import (
    DegradedReason,
    DegradedResponse,
    FallbackTier,
    make_degraded_response,
)
from app.ml.registry import ModelRegistry, model_registry

logger = logging.getLogger(__name__)


class VRAMRefusalError(Exception):
    """Base exception for inference jobs refused due to GPU or VRAM constraints."""

    def __init__(
        self,
        reason: str,
        message: str,
        model_id: Optional[str] = None,
        required_bytes: Optional[int] = None,
        available_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
    ):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.model_id = model_id
        self.required_bytes = required_bytes
        self.available_bytes = available_bytes
        self.total_bytes = total_bytes

    def to_degraded_response(
        self, fallback_tier: str = FallbackTier.REFUSAL.value
    ) -> DegradedResponse:
        """Convert refusal to the typed DegradedResponse contract."""
        req_gb = (
            round(self.required_bytes / (1024 ** 3), 2)
            if self.required_bytes is not None
            else None
        )
        avail_gb = (
            round(self.available_bytes / (1024 ** 3), 2)
            if self.available_bytes is not None
            else None
        )
        return make_degraded_response(
            reason=self.reason,
            message=self.message,
            model_id=self.model_id,
            vram_required_gb=req_gb,
            vram_available_gb=avail_gb,
            fallback_tier=fallback_tier,
            details={
                "total_bytes": self.total_bytes,
                "required_bytes": self.required_bytes,
                "available_bytes": self.available_bytes,
            },
        )


class NoGPUError(VRAMRefusalError):
    """Raised when no CUDA GPU is detected or available on host."""

    def __init__(
        self,
        message: str = "No CUDA GPU available on host",
        model_id: Optional[str] = None,
    ):
        super().__init__(
            reason=DegradedReason.NO_GPU.value,
            message=message,
            model_id=model_id,
            required_bytes=None,
            available_bytes=0,
            total_bytes=0,
        )


class InsufficientVRAMError(VRAMRefusalError):
    """Raised when available free GPU VRAM is less than model requirement + overhead."""

    def __init__(
        self,
        model_id: str,
        required_bytes: int,
        available_bytes: int,
        total_bytes: int,
        message: Optional[str] = None,
    ):
        req_gb = required_bytes / (1024 ** 3)
        avail_gb = available_bytes / (1024 ** 3)
        msg = message or (
            f"Insufficient VRAM for model '{model_id}': "
            f"requires {req_gb:.2f} GB (including overhead), "
            f"but only {avail_gb:.2f} GB free."
        )
        super().__init__(
            reason=DegradedReason.INSUFFICIENT_VRAM.value,
            message=msg,
            model_id=model_id,
            required_bytes=required_bytes,
            available_bytes=available_bytes,
            total_bytes=total_bytes,
        )


class ModelNotFoundError(VRAMRefusalError):
    """Raised when the requested model_id is not present in the registry."""

    def __init__(self, model_id: str, message: Optional[str] = None):
        super().__init__(
            reason=DegradedReason.MODEL_NOT_FOUND.value,
            message=message or f"Model '{model_id}' is not registered in ModelRegistry",
            model_id=model_id,
            required_bytes=None,
            available_bytes=None,
            total_bytes=None,
        )


class VRAMGuard:
    """VRAM admission guard before executing inference jobs."""

    DEFAULT_OVERHEAD_GB = 1.0

    def __init__(
        self,
        registry: Optional[ModelRegistry] = None,
        default_overhead_gb: float = 1.0,
    ):
        self.registry = registry or model_registry
        self.default_overhead_gb = default_overhead_gb

    def get_gpu_info(self, device: int = 0) -> Dict[str, Any]:
        """Query GPU presence and VRAM without crashing if torch/CUDA is missing."""
        try:
            import torch  # type: ignore

            if not torch.cuda.is_available() or torch.cuda.device_count() == 0:
                return {
                    "available": False,
                    "device_name": None,
                    "total_bytes": 0,
                    "free_bytes": 0,
                    "used_bytes": 0,
                    "total_gb": 0.0,
                    "free_gb": 0.0,
                    "used_gb": 0.0,
                    "vram_percent": 0.0,
                }
            device_name = torch.cuda.get_device_name(device)
            free_bytes, total_bytes = torch.cuda.mem_get_info(device)
            used_bytes = total_bytes - free_bytes
            return {
                "available": True,
                "device_name": device_name,
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": used_bytes,
                "total_gb": round(total_bytes / (1024 ** 3), 2),
                "free_gb": round(free_bytes / (1024 ** 3), 2),
                "used_gb": round(used_bytes / (1024 ** 3), 2),
                "vram_percent": (
                    round((used_bytes / total_bytes) * 100, 1)
                    if total_bytes > 0
                    else 0.0
                ),
            }
        except (ImportError, Exception):
            return {
                "available": False,
                "device_name": None,
                "total_bytes": 0,
                "free_bytes": 0,
                "used_bytes": 0,
                "total_gb": 0.0,
                "free_gb": 0.0,
                "used_gb": 0.0,
                "vram_percent": 0.0,
            }

    def check_vram(
        self,
        model_id: str,
        working_overhead_gb: Optional[float] = None,
        device: int = 0,
    ) -> Dict[str, Any]:
        """Check whether model + overhead fits into GPU free VRAM.

        Resolves the model in the registry *first* so an unknown id is reported as
        `model_not_found` regardless of whether this host has a GPU.

        Raises ModelNotFoundError if the model is not registered.
        Raises NoGPUError if CUDA GPU is not available.
        Raises InsufficientVRAMError if free VRAM is too low even with offload.
        Returns dict with admission details on success, including `mode`:
        "resident" (model already loaded), "full" or "offload".
        """
        try:
            meta = self.registry.get(model_id)
        except KeyError:
            raise ModelNotFoundError(model_id=model_id)

        gpu = self.get_gpu_info(device=device)
        if not gpu["available"]:
            raise NoGPUError(model_id=model_id)

        overhead_gb = (
            working_overhead_gb
            if working_overhead_gb is not None
            else self.default_overhead_gb
        )
        overhead_bytes = int(overhead_gb * (1024 ** 3))

        # If already resident, only working overhead is required.
        if self.registry.is_loaded(model_id):
            required_bytes = overhead_bytes
            mode = "resident"
        else:
            required_bytes = meta.approx_vram_bytes + overhead_bytes
            mode = "full"

        free_bytes = gpu["free_bytes"]
        total_bytes = gpu["total_bytes"]

        # Fall back to the CPU-offload footprint when the fully resident footprint
        # will not fit. Decision #1 sets the floor at 16 GB, where SVD (16 GB
        # resident) only fits via its 8 GB offload profile.
        if (
            mode == "full"
            and free_bytes < required_bytes
            and meta.offload_vram_bytes is not None
        ):
            offload_bytes = meta.offload_vram_bytes + overhead_bytes
            if free_bytes >= offload_bytes:
                required_bytes = offload_bytes
                mode = "offload"

        if free_bytes < required_bytes:
            # An admission attempt would raise InsufficientVRAMError.
            # Keep ONLY the model we are about to load: a resident sibling
            # candidate (e.g. SDXL while FLUX is the priority pick) must not
            # pin VRAM and force an avoidable downgrade.
            # Invariant: because callers run under INFERENCE_LOCK, eviction can
            # never run while another request is mid-inference.
            evicted = self.registry.evict_except({model_id})
            if evicted:
                gpu = self.get_gpu_info(device=device)
                free_bytes = gpu["free_bytes"]
                total_bytes = gpu["total_bytes"]
                if (
                    mode == "full"
                    and free_bytes < required_bytes
                    and meta.offload_vram_bytes is not None
                ):
                    offload_bytes = meta.offload_vram_bytes + overhead_bytes
                    if free_bytes >= offload_bytes:
                        required_bytes = offload_bytes
                        mode = "offload"

        if free_bytes < required_bytes:
            raise InsufficientVRAMError(
                model_id=model_id,
                required_bytes=required_bytes,
                available_bytes=free_bytes,
                total_bytes=total_bytes,
            )

        return {
            "admitted": True,
            "model_id": model_id,
            "mode": mode,
            "required_gb": round(required_bytes / (1024 ** 3), 2),
            "free_gb": round(free_bytes / (1024 ** 3), 2),
            "total_gb": round(total_bytes / (1024 ** 3), 2),
            "already_loaded": self.registry.is_loaded(model_id),
        }

    def select_fitting_model(
        self,
        candidate_ids: List[str],
        working_overhead_gb: Optional[float] = None,
        device: int = 0,
    ) -> str:
        """Select first model from candidate_ids that fits into VRAM.

        Implements Decision #4 auto-downgrade (e.g. ['flux-schnell', 'sdxl']).
        Unknown candidates are skipped rather than aborting the whole selection.
        If none fit, raises InsufficientVRAMError for the primary candidate or NoGPUError.
        """
        if not candidate_ids:
            raise VRAMRefusalError(
                reason=DegradedReason.MODEL_NOT_FOUND.value,
                message="No candidate models were supplied for selection",
            )

        gpu = self.get_gpu_info(device=device)
        if not gpu["available"]:
            raise NoGPUError(model_id=candidate_ids[0])

        first_insufficient_err = None
        for mid in candidate_ids:
            try:
                self.check_vram(
                    mid,
                    working_overhead_gb=working_overhead_gb,
                    device=device,
                )
                return mid
            except ModelNotFoundError:
                logger.warning(f"Candidate model '{mid}' is not registered; skipping")
                continue
            except InsufficientVRAMError as err:
                if first_insufficient_err is None:
                    first_insufficient_err = err

        if first_insufficient_err is not None:
            raise first_insufficient_err

        raise VRAMRefusalError(
            reason=DegradedReason.MODEL_NOT_FOUND.value,
            message=(
                "No suitable model could be selected from candidates: "
                f"{', '.join(candidate_ids)}"
            ),
            model_id=candidate_ids[0],
        )


# Global singleton instance
vram_guard = VRAMGuard()
