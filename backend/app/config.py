import os
from pydantic_settings import BaseSettings

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

    class Config:
        case_sensitive = True

settings = Settings()
