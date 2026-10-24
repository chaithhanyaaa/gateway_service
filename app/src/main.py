import os
from app.src.core.config import Settings

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from app.src.core.logging_config import setup_logging
from app.src.core.request_id_middleware import RequestIdMiddleware
from app.src.routers.chatRouter import router as gateway_router

load_dotenv()

# Initialize logging before serving requests.
setup_logging()

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