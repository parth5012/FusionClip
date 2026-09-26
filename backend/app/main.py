import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_db
from app.routers import export, generate, media, settings as settings_router, storage, tasks, upscale
from app.services.secrets import warn_if_dev_secret_key
from app.storage import init_storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Events
    logger.info("Initializing FusionClip databases and storage stacks...")
    warn_if_dev_secret_key()
    init_db()
    init_storage()
    yield
    # Shutdown Events
    logger.info("Shutting down FusionClip backend...")


app = FastAPI(
    title="FusionClip API",
    description="Backend API services for FusionClip multimedia management and generation dashboard",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Map validation errors to 400 for /api/export per API contract, retaining 422 elsewhere."""
    if request.url.path.startswith("/api/export"):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# Configure CORS for the Next.js frontend. An explicit origin list is required
# because allow_credentials=True is incompatible with a wildcard origin.
# allow_credentials is False because the app has no cookies, sessions or auth
# (see ADR-0001); retaining True would be the sole reason a wildcard CORS
# origin is dangerous (L-6).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {
        "app": "FusionClip API Portal",
        "status": "Green",
        "database": "pgvector ready",
        "storage": "MinIO S3 integration live",
    }


app.include_router(storage.router)
app.include_router(tasks.router)
app.include_router(settings_router.router)
app.include_router(generate.router)
app.include_router(media.router)
app.include_router(upscale.router)
app.include_router(export.router)
