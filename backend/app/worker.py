from arq.connections import RedisSettings

from app.core.config import Settings
from app.features.tasks.queue import redis_settings_from_url
from app.features.tasks.worker import generate_embeddings_task, parse_document_task

settings = Settings()


class WorkerSettings:
    functions = [parse_document_task, generate_embeddings_task]
    redis_settings: RedisSettings = redis_settings_from_url(settings.redis_url)
    queue_name = "commercelens:tasks"
    max_jobs = 4
    max_tries = 3
    job_timeout = 120
    keep_result = 0
