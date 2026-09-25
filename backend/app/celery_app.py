from celery import Celery
from app.config import settings
from kombu import Queue

celery = Celery(
    "fusionclip",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"]
)

# Standard celery configuration settings
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Solo pool is recommended for windows if running locally outside docker
    worker_concurrency=4,
    # GPU tasks hold VRAM for their whole runtime; prefetching >1 would reserve
    # several multi-GB models at once on a 16 GB card. Also ack late so an
    # interrupted GPU job is re-delivered instead of silently lost.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# Define task queues
celery.conf.task_queues = (
    Queue('media.fast'),
    Queue('media.heavy'),
    Queue('media.gpu'),
)

# Map tasks to queues
celery.conf.task_routes = {
    'app.tasks.process_media_fast': {'queue': 'media.fast'},
    'app.tasks.process_media_heavy': {'queue': 'media.heavy'},
    'app.tasks.generate_media_embedding': {'queue': 'media.fast'},
    'app.tasks.extract_media_subtitles': {'queue': 'media.fast'},

    'app.tasks.process_gpu_task': {'queue': 'media.gpu'},
}

# Register Celery task boundary lifecycle logging signals (#108)
import app.task_logging  # noqa: F401

