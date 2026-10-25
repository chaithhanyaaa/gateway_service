from app.src.core.redis_client import redis_client



RETRY_FAILED_OPERATION_SCRIPT = """
if redis.call("HGET", KEYS[1], "status") ~= "FAILED" then
    return 0
end

redis.call("DEL", KEYS[2])

redis.call(
    "HSET", KEYS[1],
    "status", "RUNNING",
    "chunk_count", 0
)

redis.call("HDEL", KEYS[1], "error")

return 1
"""


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
    )

    return result == 1


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

return 1
"""

# first reserve the key value pair in redis 
async def claim_operation(
    operation_id: str,
    user_id: str,
    fingerprint: str,
) -> bool:
    key = f"operation:{user_id}:{operation_id}"

    result = await redis_client.eval(
        CLAIM_OPERATION_SCRIPT,
        1,            # Number of Redis keys passed
        key,          # KEYS[1]
        user_id,      # ARGV[1]
        fingerprint,  # ARGV[2]
    )

    return result == 1


#after creating the opeartion we can append the chunks 
async def append_chunk(operation_key: str, user_id: str, chunk: str) -> None:
    key = f"operation:{user_id}:{operation_key}:chunks"

    await redis_client.rpush(key, chunk)

#we set the status done/completed
async def complete_operation(operation_key: str, user_id: str) -> None:
    key = f"operation:{user_id}:{operation_key}"

    await redis_client.hset(key, "status", "COMPLETED")

# if opeartion fails we set the status to failed and store the error message in redis
async def fail_operation(operation_key: str, user_id: str, error: str) -> None:
    key = f"operation:{user_id}:{operation_key}"

    await redis_client.hset(
        key,
        mapping={
            "status": "FAILED",
            "error": error,
        },
    )