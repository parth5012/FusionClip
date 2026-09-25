"""Model registry with lazy load/unload for local PyTorch pipelines (#99).

Holds the pinned model roster from ticket #98:
- FLUX.1 [schnell] (FP8, ~13-16 GB, Apache-2.0)
- SDXL (FP8, ~6-8 GB, OpenRAIL++-M)
- XTTS v2 (FP16, ~4-6 GB, CPML)
- MusicGen large (FP16, ~10.4 GB, CC-BY-NC-4.0 weights)
- Stable Video Diffusion (FP16, ~16 GB resident / 8 GB offload, Stability AI Community)

Loading is strictly lazy and idempotent.
Unloading drops resident instances and invokes GPU cache release.
Lifecycle mutations are serialized behind a lock so two concurrent Celery workers
cannot both lazy-load the same multi-GB model and OOM the GPU.
"""

from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ModelMetadata(BaseModel):
    """Metadata describing a local inference model in the registry."""

    model_id: str = Field(..., description="Unique model identifier")
    family: str = Field(..., description="Pipeline family: image, voice, audio, video")
    dtype_quant: str = Field(..., description="Quantization/precision, e.g. fp8, fp16")
    approx_vram_gb: float = Field(
        ..., description="Approximate VRAM requirement in gigabytes"
    )
    license: str = Field(..., description="Model license identifier")
    description: Optional[str] = Field(
        default=None, description="Human-readable description"
    )
    offload_vram_gb: Optional[float] = Field(
        default=None, description="VRAM requirement when CPU offload is active"
    )

    @property
    def approx_vram_bytes(self) -> int:
        """Approximate VRAM requirement in bytes."""
        return int(self.approx_vram_gb * (1024 ** 3))

    @property
    def offload_vram_bytes(self) -> Optional[int]:
        """Offloaded VRAM requirement in bytes if applicable."""
        if self.offload_vram_gb is not None:
            return int(self.offload_vram_gb * (1024 ** 3))
        return None


class ModelEntry:
    """Internal container tracking an individual model's lifecycle and handle."""

    def __init__(
        self,
        metadata: ModelMetadata,
        loader_handle: Optional[Callable[[], Any]] = None,
    ):
        self.metadata = metadata
        self.loader_handle = loader_handle
        self.instance: Any = None
        self.loaded_at: Optional[float] = None

    @property
    def is_loaded(self) -> bool:
        return self.instance is not None


# Pinned roster matching tickets #97 and #98
PINNED_ROSTER: List[ModelMetadata] = [
    ModelMetadata(
        model_id="flux-schnell",
        family="image",
        dtype_quant="fp8",
        approx_vram_gb=13.0,
        license="Apache-2.0",
        description="FLUX.1 [schnell] 4-step image generation at FP8",
    ),
    ModelMetadata(
        model_id="sdxl",
        family="image",
        dtype_quant="fp8",
        approx_vram_gb=6.5,
        license="OpenRAIL++-M",
        description="Stable Diffusion XL base at FP8 (auto-downgrade fallback)",
    ),
    ModelMetadata(
        model_id="xtts-v2",
        family="voice",
        dtype_quant="fp16",
        approx_vram_gb=4.0,
        license="CPML",
        description="Coqui XTTS v2 text-to-speech and zero-shot voice cloning",
    ),
    ModelMetadata(
        model_id="musicgen",
        family="audio",
        dtype_quant="fp16",
        approx_vram_gb=10.4,
        # Weights are CC-BY-NC-4.0; only the code is MIT. The weights license is
        # what gates usage, so that is what the registry reports.
        license="CC-BY-NC-4.0",
        description="MusicGen large text-to-music model, weights CC-BY-NC-4.0 (isolated runtime)",
    ),
    ModelMetadata(
        model_id="svd",
        family="video",
        dtype_quant="fp16",
        approx_vram_gb=16.0,
        offload_vram_gb=8.0,
        # Stability AI Community License - OpenRAIL++-M is SDXL's license, not SVD's.
        license="Stability-AI-Community",
        description="Stable Video Diffusion img2vid-xt (16 GB resident / 8 GB offload)",
    ),
]


class ModelRegistry:
    """Registry managing model metadata and lazy resident lifecycle."""

    def __init__(self, populate_defaults: bool = True):
        self._models: Dict[str, ModelEntry] = {}
        # Guards the load/unload/register lifecycle: without it two workers can
        # both observe `is_loaded == False` and allocate the same model twice.
        self._lock = threading.RLock()
        if populate_defaults:
            for meta in PINNED_ROSTER:
                self.register(meta)

    def register(
        self,
        metadata: ModelMetadata,
        loader_handle: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Register or update a model in the registry.

        If the same model_id is already resident, it is unloaded first so its VRAM
        is reclaimed instead of being orphaned when the old entry is dropped.
        """
        with self._lock:
            existing = self._models.get(metadata.model_id)
            if existing is not None and existing.is_loaded:
                logger.warning(
                    f"Re-registering resident model '{metadata.model_id}'; "
                    "unloading first to release VRAM"
                )
                self.unload_model(metadata.model_id)
            self._models[metadata.model_id] = ModelEntry(
                metadata=metadata, loader_handle=loader_handle
            )

    def unregister(self, model_id: str) -> bool:
        """Unload and remove a model from the registry."""
        with self._lock:
            if model_id in self._models:
                self.unload_model(model_id)
                del self._models[model_id]
                return True
            return False

    def get(self, model_id: str) -> ModelMetadata:
        """Retrieve model metadata by id. Raises KeyError if not registered."""
        if model_id not in self._models:
            raise KeyError(f"Model '{model_id}' is not registered in ModelRegistry")
        return self._models[model_id].metadata

    def list_models(self) -> List[ModelMetadata]:
        """Return list of all registered model metadata."""
        return [entry.metadata for entry in self._models.values()]

    def is_loaded(self, model_id: str) -> bool:
        """Check if model is currently resident in memory."""
        if model_id not in self._models:
            return False
        return self._models[model_id].is_loaded

    def load_model(
        self,
        model_id: str,
        loader_handle: Optional[Callable[[], Any]] = None,
    ) -> Any:
        """Lazy and idempotent model load.

        Returns existing cached instance if already loaded.
        Otherwise executes loader_handle and caches the result.
        Serialized so the loader runs at most once across concurrent callers.
        """
        with self._lock:
            if model_id not in self._models:
                raise KeyError(
                    f"Model '{model_id}' is not registered in ModelRegistry"
                )

            entry = self._models[model_id]
            if entry.is_loaded:
                return entry.instance

            loader = loader_handle or entry.loader_handle
            if loader is None:
                raise ValueError(
                    f"No loader configured for model '{model_id}'. Provide a loader_handle."
                )

            logger.info(f"Lazy loading model '{model_id}' into memory...")
            start_t = time.time()
            instance = loader()
            entry.instance = instance
            entry.loaded_at = time.time()
            logger.info(
                f"Successfully loaded '{model_id}' in {entry.loaded_at - start_t:.2f}s"
            )
            return instance

    def unload_model(self, model_id: str) -> bool:
        """Idempotently unload a model and reclaim VRAM."""
        with self._lock:
            if model_id not in self._models:
                return False

            entry = self._models[model_id]
            if not entry.is_loaded:
                return False

            logger.info(f"Unloading model '{model_id}' and freeing VRAM...")
            entry.instance = None
            entry.loaded_at = None

            # Force garbage collection and CUDA cache empty
            gc.collect()
            self._empty_cuda_cache()
            return True

    def unload_all(self) -> int:
        """Unload all currently loaded models. Returns count of unloaded models."""
        with self._lock:
            count = 0
            for model_id in list(self._models.keys()):
                if self.is_loaded(model_id):
                    if self.unload_model(model_id):
                        count += 1
            return count

    def reset(self) -> None:
        """Reset registry to default state."""
        with self._lock:
            self.unload_all()
            self._models.clear()
            for meta in PINNED_ROSTER:
                self.register(meta)

    @staticmethod
    def _empty_cuda_cache() -> None:
        """Safely empty CUDA cache if torch and CUDA are available."""
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except (ImportError, Exception):
            pass


# Global singleton instance
model_registry = ModelRegistry()
