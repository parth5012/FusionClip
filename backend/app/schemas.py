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


class GenerationAnalyzedFile(BaseModel):
    """One uploaded media file handed to the Gemini multimodal pipeline."""

    filename: str
    original_name: str
    content_type: str
    url: str
    gemini_file: Optional[str] = None
    gemini_uri: Optional[str] = None


class GenerationMultimodalOut(GenerationOut):
    """Response from /api/generate/text when media files are attached."""

    output: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    analyzed_files: List[GenerationAnalyzedFile] = Field(default_factory=list)


class GenerationGeminiImageOut(GenerationOut):
    prompt: str
    model: str
    filename: str
    url: str
    content_type: str


class GenerationGeminiVideoOut(GenerationOut):
    prompt: str
    model: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    url: Optional[str] = None
    filename: Optional[str] = None


class GenerationAudioOut(GenerationOut):
    type: str
    filename: str
    url: str


class GenerationTtsOut(GenerationOut):
    """Response from POST /api/generate/tts (real ElevenLabs synthesis)."""

    voice_id: str
    model: str
    stability: float
    clarity: float
    filename: str
    url: str
    content_type: str


class GenerationVoice(BaseModel):
    """One ElevenLabs voice surfaced by the voice-list endpoint."""

    voice_id: str
    name: Optional[str] = None
    labels: Dict[str, str] = Field(default_factory=dict)
    category: Optional[str] = None
    preview_url: Optional[str] = None


class GenerationVoiceListOut(GenerationOut):
    voices: List[GenerationVoice] = Field(default_factory=list)


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


# --- Batch Export ---------------------------------------------------------


class BatchExportIn(BaseModel):
    paths: list[str] = Field(..., min_length=1)
    format: str = "original"


class BatchExportOut(BaseModel):
    message: str
    task_id: str
    status: str
