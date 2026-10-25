from redis.asyncio import Redis

from app.src.core.config import settings


redis_client = Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    decode_responses=True, #Redis returns strings instead of byte strings for text responses
    socket_connect_timeout=5, # Allow up to 5 seconds to establish a connection
    socket_timeout=5, # allow 5 sec for read/write operation
)


async def close_redis() -> None:
    await redis_client.aclose()

async def check_redis_connection() -> None:
    await redis_client.ping()