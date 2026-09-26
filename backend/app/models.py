import datetime
import sqlalchemy
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, Table, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    from sqlalchemy.types import TypeDecorator

    class Vector(TypeDecorator):
        """Fallback PGVector type using JSON/Array representation when pgvector not installed."""
        impl = JSON
        cache_ok = True

        def __init__(self, dim=384):
            super().__init__()
            self.dim = dim

        def process_bind_param(self, value, dialect):
            return value

        def process_result_value(self, value, dialect):
            return value


asset_tags = Table(
    "asset_tags",
    Base.metadata,
    Column("asset_id", Integer, ForeignKey("media_assets.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    assets = relationship("MediaAsset", secondary=asset_tags, back_populates="tags")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    content_type = Column(String, nullable=False)
    duration = Column(Float, nullable=True)
    embedding = Column(Vector(384), nullable=True)
    # Optional link to the source asset this one was derived from (e.g. an
    # upscaled output pointing at the original it was generated from).
    # Used by the before/after comparison UI to pair originals with results.
    source_path = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    tags = relationship("Tag", secondary=asset_tags, back_populates="assets", lazy="selectin")


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
    error_type = Column(String, nullable=True)
    traceback = Column(Text, nullable=True)
    logs = Column(Text, nullable=True)

    retry_count = Column(Integer, default=0, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    last_retry_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
