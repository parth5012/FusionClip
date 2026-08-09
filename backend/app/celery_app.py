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
    worker_concurrency=4
)

# Define task queues
celery.conf.task_queues = (
    Queue('media.fast'),
    Queue('media.heavy'),
)

# Map tasks to queues
celery.conf.task_routes = {
    'app.tasks.process_media_fast': {'queue': 'media.fast'},
    'app.tasks.process_media_heavy': {'queue': 'media.heavy'},
    'app.tasks.generate_media_embedding': {'queue': 'media.fast'},
}
