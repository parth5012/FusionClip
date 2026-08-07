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
