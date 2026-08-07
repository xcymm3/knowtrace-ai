from __future__ import annotations

from urllib.parse import unquote, urlparse
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings

from app.core.errors import ApiError


def redis_settings_from_url(redis_url: str | None) -> RedisSettings:
    if not redis_url:
        raise ApiError(503, "REDIS_NOT_CONFIGURED", "Redis 尚未完成配置。")

    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ApiError(503, "REDIS_CONFIGURATION_INVALID", "REDIS_URL 配置无效。")

    return RedisSettings(
        host=parsed.hostname,
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=unquote(parsed.password) if parsed.password else None,
        ssl=parsed.scheme == "rediss",
    )


class ArqTaskQueue:
    def __init__(self, redis_url: str | None) -> None:
        self._redis_settings = redis_settings_from_url(redis_url)

    async def enqueue_parse_document(self, task_id: UUID) -> None:
        await self._enqueue("parse_document_task", task_id, "parse-document")

    async def enqueue_generate_embeddings(self, task_id: UUID) -> None:
        await self._enqueue("generate_embeddings_task", task_id, "generate-embeddings")

    async def _enqueue(self, function_name: str, task_id: UUID, job_type: str) -> None:
        redis = await create_pool(self._redis_settings)
        try:
            await redis.enqueue_job(
                function_name,
                str(task_id),
                _job_id=f"{job_type}:{task_id}",
                _queue_name="knowtrace:tasks",
            )
        except Exception as error:
            raise ApiError(503, "TASK_QUEUE_UNAVAILABLE", "资料解析队列暂时不可用。") from error
        finally:
            await redis.aclose()
