import logging
import os
from typing import List

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Development-only placeholder for the secret-store master key. Any deployment
# still running with this value is logged loudly at startup (see
# app.services.secrets.warn_if_dev_secret_key).
DEV_DEFAULT_SECRET_KEY = "fusionclip-dev-insecure-key-change-me"


class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql://fusionclip:fusionclip123@db:5432/fusionclip"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    
    # MinIO
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ROOT_USER: str = os.getenv("MINIO_ROOT_USER", "fusionclip_admin")
    MINIO_ROOT_PASSWORD: str = os.getenv("MINIO_ROOT_PASSWORD", "fusionclip_password123")
    MINIO_BUCKET_NAME: str = os.getenv("MINIO_BUCKET_NAME", "fusionclip-media")
    MINIO_USE_SSL: bool = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
    MINIO_EXTERNAL_ENDPOINT: str = os.getenv(
        "MINIO_EXTERNAL_ENDPOINT", "http://localhost:9000"
    )

    # CORS — comma separated list of allowed browser origins. A wildcard is
    # deliberately NOT the default: allow_credentials=True with "*" is rejected
    # by browsers and would leak credentials. A wildcard in the env var is
    # rejected loudly (mirrors warn_if_dev_secret_key) so the dangerous
    # combination can never be configured by accident.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")

    # Master key used to Fernet-encrypt third-party provider API keys stored in
    # the `configurations` table under the `secret.` prefix.
    FUSIONCLIP_SECRET_KEY: str = os.getenv(
        "FUSIONCLIP_SECRET_KEY", DEV_DEFAULT_SECRET_KEY
    )

    # --- Skin enhancement: operator-supplied third-party checkouts -------------
    #
    # Both engines in app/ml/skin_enhancer.py are local-only, and neither is fully
    # installable from PyPI into this app's environment:
    #
    # * XPixelGroup/DiffBIR (Apache-2.0) is NOT on PyPI. It is a research repo that
    #   has to be cloned with its submodules (`git clone --recursive`) and run from
    #   its own root, because inference.py loads its configs with the
    #   CWD-relative `OmegaConf.load("configs/inference/swinir.yaml")`. Its pinned
    #   torch is `2.2.2+cu118` with `xformers==0.0.25.post1+cu118`, which normally
    #   cannot coexist with this app's own torch, hence DIFFBIR_PYTHON below.
    # * GFPGAN *is* on PyPI and is a normal dependency (see requirements.txt). The
    #   model path is configurable only so an air-gapped operator can point at a
    #   pre-downloaded checkpoint instead of letting GFPGANer fetch the release
    #   asset over the network on first load.
    #
    # When DIFFBIR_REPO_PATH is unset or wrong, Creative/Flexible requests return
    # the labeled degraded envelope naming this setting. Nothing is fabricated.
    DIFFBIR_REPO_PATH: str = os.getenv("DIFFBIR_REPO_PATH", "")
    #: Interpreter used to run DiffBIR's inference.py. Defaults to this app's own
    #: interpreter, which is only correct when DiffBIR's deps happen to be
    #: installed alongside ours - in practice they live in their own venv.
    DIFFBIR_PYTHON: str = os.getenv("DIFFBIR_PYTHON", "")
    #: Hard wall-clock ceiling on one DiffBIR invocation. INFERENCE_LOCK
    #: serialises every inference request in the process, so a wedged subprocess
    #: with no timeout would stall all of image, audio and skin work. Generous
    #: because a cold start loads five models (SwinIR x2, ControlLDM, SD 2.1,
    #: the diffusion schedule) and fetches their weights on first run.
    DIFFBIR_TIMEOUT_SECONDS: float = float(
        os.getenv("DIFFBIR_TIMEOUT_SECONDS", "600")
    )
    GFPGAN_MODEL_PATH: str = os.getenv("GFPGAN_MODEL_PATH", "")

    @property
    def CORS_ORIGINS_LIST(self) -> List[str]:
        """CORS_ORIGINS parsed into a list of individual origins.

        Rejects a wildcard origin: pairing "*" with allow_credentials=True is
        the exact anti-pattern T-02 was built to remove, and the secret
        endpoints now sit behind this CORS policy. A wildcard is logged loudly
        and replaced with an empty list so the dangerous combination is
        impossible by construction.
        """
        raw = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        if "*" in raw:
            logger.warning(
                "CORS_ORIGINS contains '*' (wildcard) — this is incompatible with "
                "allow_credentials and exposes unauthenticated secret endpoints. "
                "Rejecting wildcard; set explicit origins instead."
            )
            return [o for o in raw if o != "*"]
        return raw

    class Config:
        case_sensitive = True

settings = Settings()
