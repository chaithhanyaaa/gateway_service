

import asyncio

from app.src.core.redis_client import redis_client


async def main():
    await redis_client.set("gateway:test", "Redis connected")
    value = await redis_client.get("gateway:test")

    print("Redis value:", value)

    await redis_client.delete("gateway:test")
    await redis_client.aclose()


if __name__ == "__test__":
    asyncio.run(main())