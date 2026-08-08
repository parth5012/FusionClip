from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import text
from app.config import settings
import logging

logger = logging.getLogger(__name__)

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """Initialize database, including pgvector extension."""
    try:
        with engine.connect() as conn:
            # Enable pgvector extension
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
        logger.info("Successfully enabled pgvector extension.")
    except Exception as e:
        logger.error(f"Failed to enable pgvector extension or connect to database: {e}")

    # Import and mount models, automatically run base schema creation engine metadata
    from app.models import MediaAsset, Configuration, Task
    Base.metadata.create_all(bind=engine)
    logger.info("Successfully auto-created all database schemas.")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
