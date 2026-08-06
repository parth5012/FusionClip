import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, func
from app.database import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    from sqlalchemy.types import TypeDecorator
    
    class Vector(TypeDecorator):
        """Fallback PGVector type using JSON/Array representation if pgvector is not installed."""
        impl = JSON
        cache_ok = True

        def __init__(self, dim=1536):
            super().__init__()
            self.dim = dim

        def process_bind_param(self, value, dialect):
            return value

        def process_result_value(self, value, dialect):
            return value

class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    content_type = Column(String, nullable=False)
    duration = Column(Float, nullable=True)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class Configuration(Base):
    __tablename__ = "configurations"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
