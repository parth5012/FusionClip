import os
from typing import List

from pydantic_settings import BaseSettings

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
    # by browsers and would leak credentials.
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")

    # Master key used to Fernet-encrypt third-party provider API keys stored in
    # the `configurations` table under the `secret.` prefix.
    FUSIONCLIP_SECRET_KEY: str = os.getenv(
        "FUSIONCLIP_SECRET_KEY", DEV_DEFAULT_SECRET_KEY
    )

    @property
    def CORS_ORIGINS_LIST(self) -> List[str]:
        """CORS_ORIGINS parsed into a list of individual origins."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    class Config:
        case_sensitive = True

settings = Settings()
