import os
from app.src.core.config import Settings
from app.src.core.redis_client import check_redis_connection,close_redis
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.src.core.logging_config import setup_logging
from app.src.core.request_id_middleware import RequestIdMiddleware
from app.src.routers.chatRouter import router as gateway_router

load_dotenv()

# Initialize logging before serving requests.
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await check_redis_connection()
    print("Redis connected successfully")

    yield

    await close_redis()
    print("Redis connection closed")

app = FastAPI(title="LLM Gateway")

# Register middleware.
app.add_middleware(RequestIdMiddleware)

# Register routes.
app.include_router(gateway_router)


if __name__ == "__main__":
    port = int(Settings().PORT)
    print(port)

    uvicorn.run(
        app,
        host=Settings().HOST,
        port=port,
        log_config=None,
    )