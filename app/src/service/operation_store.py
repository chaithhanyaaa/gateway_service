
from app.src.core.redis_client import redis_client

OPERATION_TTL_SECONDS = 300  # 5 minutes
RUNNING_TTL_SECONDS = 600    # 10 minutes


CLAIM_OPERATION_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 1 then
    return 0
end

redis.call(
    "HSET", KEYS[1],
    "status", "RUNNING",
    "user_id", ARGV[1],
    "fingerprint", ARGV[2],
    "chunk_count", 0
)

redis.call("EXPIRE", KEYS[1], ARGV[3])
redis.call("EXPIRE", KEYS[2], ARGV[3])

return 1
"""




APPEND_CHUNKS_SCRIPT = """
if redis.call("HGET", KEYS[1], "status") ~= "RUNNING" then
    return 0
end

local chunk_count = #ARGV - 1
local ttl = ARGV[#ARGV]

if chunk_count <= 0 then
    return 1
end

for i = 1, chunk_count do
    redis.call("RPUSH", KEYS[2], ARGV[i])
end

redis.call("HINCRBY", KEYS[1], "chunk_count", chunk_count)
redis.call("EXPIRE", KEYS[1], ttl)
redis.call("EXPIRE", KEYS[2], ttl)

return 1
"""

FINALIZE_OPERATION_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
    return 0
end

redis.call("HSET", KEYS[1], "status", ARGV[1])

if ARGV[1] == "FAILED" then
    redis.call("HSET", KEYS[1], "error", ARGV[3])
else
    redis.call("HDEL", KEYS[1], "error")
end

redis.call("EXPIRE", KEYS[1], ARGV[2])

if redis.call("EXISTS", KEYS[2]) == 1 then
    redis.call("EXPIRE", KEYS[2], ARGV[2])
end

return 1
"""


RETRY_FAILED_OPERATION_SCRIPT = """
if redis.call("HGET", KEYS[1], "status") ~= "FAILED" then
    return 0
end

if tonumber(redis.call("HGET", KEYS[1], "chunk_count") or "0") ~= 0 then
    return 0
end

redis.call("DEL", KEYS[2])

redis.call(
    "HSET", KEYS[1],
    "status", "RUNNING",
    "chunk_count", 0
)

redis.call("HDEL", KEYS[1], "error")
redis.call("EXPIRE", KEYS[1], ARGV[1])
redis.call("EXPIRE", KEYS[2], ARGV[1])

return 1
"""


async def claim_operation(
    operation_id: str,
    user_id: str,
    fingerprint: str,
) -> bool:
    operation_key = f"operation:{user_id}:{operation_id}"
    chunks_key = f"{operation_key}:chunks"

    result = await redis_client.eval(
        CLAIM_OPERATION_SCRIPT,
        2,
        operation_key,
        chunks_key,
        user_id,
        fingerprint,
        RUNNING_TTL_SECONDS,
    )

    return result == 1

async def append_chunks(
    operation_id: str,
    user_id: str,
    chunks: list[str],
) -> None:
    if not chunks:
        return

    operation_key = f"operation:{user_id}:{operation_id}"
    chunks_key = f"{operation_key}:chunks"

    result = await redis_client.eval(
        APPEND_CHUNKS_SCRIPT,
        2,
        operation_key,
        chunks_key,
        *chunks,
        RUNNING_TTL_SECONDS,
    )

    if result != 1:
        raise RuntimeError(
            "Cannot append chunks: operation is not RUNNING"
        )

async def complete_operation(
    operation_id: str,
    user_id: str,
) -> None:
    operation_key = f"operation:{user_id}:{operation_id}"
    chunks_key = f"{operation_key}:chunks"

    await redis_client.eval(
        FINALIZE_OPERATION_SCRIPT,
        2,
        operation_key,
        chunks_key,
        "COMPLETED",
        OPERATION_TTL_SECONDS,
        "",
    )


async def fail_operation(
    operation_id: str,
    user_id: str,
    error: str,
) -> None:
    operation_key = f"operation:{user_id}:{operation_id}"
    chunks_key = f"{operation_key}:chunks"

    await redis_client.eval(
        FINALIZE_OPERATION_SCRIPT,
        2,
        operation_key,
        chunks_key,
        "FAILED",
        OPERATION_TTL_SECONDS,
        error,
    )


async def retry_failed_operation(
    operation_id: str,
    user_id: str,
) -> bool:
    operation_key = f"operation:{user_id}:{operation_id}"
    chunks_key = f"{operation_key}:chunks"

    result = await redis_client.eval(
        RETRY_FAILED_OPERATION_SCRIPT,
        2,
        operation_key,
        chunks_key,
        RUNNING_TTL_SECONDS,
    )

    return result == 1
