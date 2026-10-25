
import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, JSONResponse

from app.src.DTO.UserMessage import UserMessage
from app.src.llms.registry import get_llm_registry
from app.src.service.llmservice import llmservice
from app.src.util.utilservice import (
    parse_messages,
    get_safe_error_message,
    create_fingerprint,
)
from app.src.core.auth import get_current_user
from app.src.core.redis_client import redis_client
from app.src.service.operation_store import (
    claim_operation,
    append_chunk,
    complete_operation,
    fail_operation,
    retry_failed_operation,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def encode_sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def get_chunk_text(raw_chunk) -> str:
    """Extract text from a LangChain chunk or a plain string."""
    if isinstance(raw_chunk, str):
        return raw_chunk

    content = getattr(raw_chunk, "content", None)

    if isinstance(content, str):
        return content

    if content is not None:
        return str(content)

    return str(raw_chunk)


@router.post("/chat")
async def create_item(
    userMessage: UserMessage,
    user_id: str = Depends(get_current_user),
):
    request_start = time.perf_counter()
    operation_id = userMessage.operation_id
    logger.info(
        "Received chat request | operation_id=%s | user_id=%s | provider=%s | model=%s",
        operation_id,
        user_id,
        userMessage.provider,
        userMessage.model
    )

    messages = parse_messages(userMessage.messages)
    fingerprint = create_fingerprint(userMessage, user_id)

    # Step 1: Check whether Redis is available.
    redis_available = False

    try:
        await redis_client.ping()
        redis_available = True
    except Exception:
        logger.exception(
            "Redis unavailable; continuing without operation persistence"
        )

    # Step 2: Claim the operation or inspect an existing operation.
    if redis_available:
        try:
            claimed = await claim_operation(
                operation_id=operation_id,
                user_id=user_id,
                fingerprint=fingerprint,
            )

            operation_key = f"operation:{user_id}:{operation_id}"
            logger.info(
                "Operation claim attempt | operation_id=%s | user_id=%s | claimed=%s",
                operation_id,
                user_id,
                claimed,
            )

            if not claimed:
                existing = await redis_client.hgetall(operation_key)

                # The key may have expired or been removed between calls.
                if not existing:
                    logger.info(
                        "Operation state missing | operation_id=%s | user_id=%s",
                        operation_id,
                        user_id,
                    )
                    return JSONResponse(
                        status_code=409,
                        content={
                            "error": {
                                "code": "OPERATION_STATE_MISSING",
                                "message": (
                                    "The operation record is missing. "
                                    "Use a new operation ID to start a new request."
                                ),
                            }
                        },
                    )

                # Reject reuse of an operation ID with different input.
                if existing.get("fingerprint") != fingerprint:
                    logger.warning(
                        "Operation fingerprint mismatch | operation_id=%s | user_id=%s",
                        operation_id,
                        user_id,
                    )
                    return JSONResponse(
                        status_code=409,
                        content={
                            "error": {
                                "code": "OPERATION_ID_CONFLICT",
                                "message": (
                                    "This operation ID was already used "
                                    "for a different request."
                                ),
                            }
                        },
                    )

                status = existing.get("status")

                # Case A: The original generation already completed.
                if status == "COMPLETED":
                    chunks_key = f"{operation_key}:chunks"
                    saved_chunks = await redis_client.lrange(
                        chunks_key, 0, -1
                    )
                    logger.info(
                        "Replaying completed operation | operation_id=%s | user_id=%s | chunks=%d",
                        operation_id,
                        user_id,
                        len(saved_chunks)
                    )

                    async def replay_generator():
                        logger.info(
                            "streaming replayed chunks | operation_id=%s | user_id=%s | chunks=%d",
                            operation_id,
                            user_id,
                            len(saved_chunks)
                        )
                        for chunk in saved_chunks:
                            yield encode_sse({"text": chunk})

                        yield encode_sse({"done": True})

                    return StreamingResponse(
                        replay_generator(),
                        media_type="text/event-stream",
                    )

                # Case B: Another request is generating this operation.
                # Replay saved chunks, then poll for new chunks.
                if status == "RUNNING":
                    chunks_key = f"{operation_key}:chunks"
                    logger.info(
                        "sending from redis which is already running | operation_id=%s | user_id=%s",
                        operation_id,
                        user_id
                    )

                    async def attach_to_existing_stream():
                        index = 0
                        logger.info(
                            "streaming from redis which is already running | operation_id=%s | user_id=%s",
                            operation_id,
                            user_id
                        )

                        while True:
                            chunks = await redis_client.lrange(
                                chunks_key, index, -1
                            )

                            for chunk in chunks:
                                yield encode_sse({"text": chunk})
                                index += 1

                            current_status = await redis_client.hget(
                                operation_key, "status"
                            )

                            if current_status == "COMPLETED":
                                yield encode_sse({"done": True})
                                break

                            if current_status == "FAILED":
                                yield encode_sse(
                                    {
                                        "error": {
                                            "code": "OPERATION_FAILED",
                                            "message": (
                                                "The generation failed retry for th response."
                                            ),
                                        }
                                    }
                                )
                                break

                            await asyncio.sleep(0.25)

                      

                    return StreamingResponse(
                        attach_to_existing_stream(),
                        media_type="text/event-stream",
                    )

                # Case C: The previous generation failed.
                # Atomically reset it so only one request can retry.
                if status == "FAILED":
                    retry_claimed = await retry_failed_operation(
                        operation_id=operation_id,
                        user_id=user_id,
                    )
                    logger.info(
                        "Retry failed operation attempt | operation_id=%s | user_id=%s | retry_claimed=%s",
                        operation_id, 
                        user_id,
                        retry_claimed
                    )

                    if not retry_claimed:
                        return JSONResponse(
                            status_code=409,
                            content={
                                "error": {
                                    "code": "RETRY_CONFLICT",
                                    "message": (
                                        "The operation state changed. "
                                        "Retry the request."
                                    ),
                                }
                            },
                        )

                    # Continue below into LLM generation.
                    # redis_available remains True, so new chunks
                    # will be saved in Redis.

                else:
                    return JSONResponse(
                        status_code=409,
                        content={
                            "error": {
                                "code": "OPERATION_STATE_UNKNOWN",
                                "message": (
                                    "The existing operation has an "
                                    "unexpected state."
                                ),
                            }
                        },
                    )

        except Exception:
            logger.exception("Redis operation setup failed")

            # Do not silently generate again if this request may have
            # already claimed or reset an operation. Doing so could
            # create a duplicate generation.
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "OPERATION_STORE_UNAVAILABLE",
                        "message": (
                            "Could not safely determine the operation state. "
                            "Retry using the same operation ID."
                        ),
                    }
                },
            )

    # Step 3: Start the LLM generation.
    provider = get_llm_registry().get_provider(userMessage.provider)
    llm = llmservice(provider)

    stream_start = time.perf_counter()

    logger.info(
        "LLM streaming started | provider=%s | model=%s",
        userMessage.provider,
        userMessage.model,
    )

    stream = llm.generate(
        prompt=userMessage.prompt,
        messages=messages,
        model=userMessage.model,
    )

    iterator = stream.__aiter__()

    # Handle failures before the first chunk.
    try:
        first_chunk = await iterator.__anext__()

    except StopAsyncIteration:
        if redis_available:
            try:
                await complete_operation(operation_id, user_id)
            except Exception:
                logger.exception("Could not mark empty operation completed")

        async def empty_generator():
            yield encode_sse({"done": True})

        return StreamingResponse(
            empty_generator(),
            media_type="text/event-stream",
        )

    except Exception as exc:
        logger.exception("LLM failed before first chunk")

        if redis_available:
            try:
                _, safe_message = get_safe_error_message(exc)
                await fail_operation(
                    operation_id,
                    user_id,
                    safe_message,
                )
            except Exception:
                logger.exception("Could not persist operation failure")

        status_code, message = get_safe_error_message(exc)

        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": status_code,
                    "message": message,
                }
            },
        )

    # Step 4: Persist each chunk before sending it to the client.
    async def event_generator():
        chunk_count = 0

        try:
            raw_chunks = _prepend_first_chunk(first_chunk, iterator)

            async for raw_chunk in raw_chunks:
                chunk = get_chunk_text(raw_chunk)

                if redis_available:
                    await append_chunk(
                        operation_id,
                        user_id,
                        chunk,
                    )

                chunk_count += 1
                yield encode_sse({"text": chunk})

            if redis_available:
                await complete_operation(operation_id, user_id)

            logger.info(
                "Streaming completed | chunks=%d | duration=%.2fs | total=%.2fs",
                chunk_count,
                time.perf_counter() - stream_start,
                time.perf_counter() - request_start,
            )

            yield encode_sse({"done": True})

        except Exception as exc:
            logger.exception("Streaming or persistence failed")

            if redis_available:
                try:
                    _, safe_message = get_safe_error_message(exc)
                    await fail_operation(
                        operation_id,
                        user_id,
                        safe_message,
                    )
                except Exception:
                    logger.exception("Could not persist operation failure")

            _, safe_message = get_safe_error_message(exc)

            yield encode_sse(
                {
                    "error": {
                        "message": safe_message,
                    }
                }
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


async def _prepend_first_chunk(first_chunk, iterator):
    """Yield the already-read first chunk, followed by the remaining stream."""
    yield first_chunk

    async for chunk in iterator:
        yield chunk
