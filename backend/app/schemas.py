"""Pydantic response/request models shared across the API routers.

Every model here mirrors a response shape that already existed in the original
monolithic ``main.py``; field names and nesting must not change without also
updating the Playwright suite in ``frontend/e2e``.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, RootModel

# --- Storage ---------------------------------------------------------------


class UploadOut(BaseModel):
    message: str
    filename: str
    path: str
    url: str


class MessageOut(BaseModel):
    message: str


class FolderOut(BaseModel):
    message: str
    path: str


# --- Tasks -----------------------------------------------------------------


class TaskDispatchOut(BaseModel):
    message: str
    task_id: str
    status: str


class TaskOut(BaseModel):
    """Runtime state of a Celery job as reported by GET /api/tasks/status/{id}."""

    id: str
    state: str
    info: Any = None


# --- Local ML / GPU Health & Guard Contracts (#99) -----------------------


class ModelHealthInfo(BaseModel):
    model_id: str
    family: str
    dtype_quant: str
    approx_vram_gb: float
    license: str
    loaded: bool
    description: Optional[str] = None


class GPUVRAMMetrics(BaseModel):
    available: bool
    device_name: Optional[str] = None
    total_gb: float = 0.0
    free_gb: float = 0.0
    used_gb: float = 0.0
    vram_percent: float = 0.0


class GPUQueueMetrics(BaseModel):
    queue_name: str = "media.gpu"
    depth: int = 0
    # Task rows carry no queue column, so this counts in-flight tasks across every
    # queue (CPU + GPU). Named for what it actually measures.
    active_tasks_total: int = 0


class GPUHealthResponse(BaseModel):
    """Health metrics for local GPU compute, model states, and background queue."""

    status: str
    gpu: GPUVRAMMetrics
    models: Dict[str, ModelHealthInfo]
    queue: GPUQueueMetrics


# --- Settings --------------------------------------------------------------


class SettingsOut(RootModel[Dict[str, str]]):
    """Flat key/value settings map. Never contains `secret.`-prefixed keys."""


class SettingsSaveOut(BaseModel):
    status: str
    message: str


class ColabTunnelOut(BaseModel):
    status: str
    colab_url: str
    colab_status: str


# --- Secrets ---------------------------------------------------------------

SecretProvider = Literal["gemini", "elevenlabs"]


class SecretsIn(BaseModel):
    """Plaintext provider keys, submitted once and never read back."""

    gemini_api_key: Optional[str] = Field(default=None)
    elevenlabs_api_key: Optional[str] = Field(default=None)


class SecretStatus(BaseModel):
    configured: bool = False
    last4: Optional[str] = None


class SecretsStatusOut(BaseModel):
    gemini: SecretStatus = Field(default_factory=SecretStatus)
    elevenlabs: SecretStatus = Field(default_factory=SecretStatus)


class SecretsMutationOut(BaseModel):
    status: str
    updated: List[str] = Field(default_factory=list)


class SecretDeleteOut(BaseModel):
    status: str
    provider: str
    deleted: bool


# --- Generation ------------------------------------------------------------


class GenerationOut(BaseModel):
    """Common base for every /api/generate/* response."""

    status: str


class GenerationTextOut(GenerationOut):
    output: str


class GenerationAudioOut(GenerationOut):
    type: str
    filename: str
    url: str


class GenerationImageParameters(BaseModel):
    steps: int
    scale: float


class GenerationImageOut(GenerationOut):
    parameters: GenerationImageParameters
    filename: str
    url: str


# --- Media -----------------------------------------------------------------


class MediaAssetOut(BaseModel):
    id: int
    title: str
    file_path: str
    file_size: int
    content_type: str
    duration: Optional[float] = None
    url: str
    created_at: Optional[str] = None
