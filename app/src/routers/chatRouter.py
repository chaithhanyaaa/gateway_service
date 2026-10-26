import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.src.DTO.UserMessage import UserMessage
from app.src.core.auth import get_current_user
from app.src.core.redis_client import redis_client
from app.src.llms.registry import get_llm_registry
from app.src.service.llmservice import llmservice
from app.src.service.operation_store import (
    append_chunks,
    claim_operation,
    complete_operation,
    fail_operation,
    retry_failed_operation,
)
from app.src.util.utilservice import (
    create_fingerprint,
    get_safe_error_message,
    parse_messages,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Number of stored chunks combined into one replay SSE event.
REPLAY_BATCH_SIZE = 20

# Maximum number of Redis list entries fetched per polling iteration.
POLL_BATCH_SIZE = 100

# Delay between polling iterations for an existing operation.
POLL_INTERVAL_SECONDS = 0.25

# Number of non-empty text chunks persisted per Redis batch.
REDIS_WRITE_BATCH_SIZE = 20


def encode_sse(data: dict) -> str:
    """Encode one application-level Server-Sent Event."""
    return f"data: {json.dumps(data)}\n\n"


def get_chunk_text(raw_chunk) -> str:
    """Extract text from a LangChain chunk or plain string."""
    if isinstance(raw_chunk, str):
        return raw_chunk

    content = getattr(raw_chunk, "content", None)

    if isinstance(content, str):
        return content

    if content is not None:
        return str(content)

    return str(raw_chunk)


def replay_batches(chunks: list[str]):
    """Combine stored text chunks into larger replay SSE events."""
    for start in range(0, len(chunks), REPLAY_BATCH_SIZE):
        batch = chunks[start:start + REPLAY_BATCH_SIZE]
        combined_text = "".join(batch)

        if combined_text:
            yield encode_sse({"text": combined_text})


async def persist_failure(
    operation_id: str,
    user_id: str,
    exc: Exception,
) -> None:
    """Persist a safe error description without exposing secrets."""
    _, safe_message = get_safe_error_message(exc)

    await fail_operation(
        operation_id=operation_id,
        user_id=user_id,
        error=safe_message,
    )


def error_response(
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


@router.post("/chat")
async def create_item(
    userMessage: UserMessage,
    user_id: str = Depends(get_current_user),
):
    request_start = time.perf_counter()
    operation_id = userMessage.operation_id

    # ---------------------------------------------------------
    # 1. Validate the idempotency key.
    # ---------------------------------------------------------
    if not operation_id:
        return error_response(
            422,
            "OPERATION_ID_REQUIRED",
            "Provide a unique operation_id.",
        )

    logger.info(
        "Chat request received | operation_id=%s | "
        "provider=%s | model=%s",
        operation_id,
        userMessage.provider,
        userMessage.model,
    )

    # ---------------------------------------------------------
    # 2. Parse the incoming messages.
    # ---------------------------------------------------------
    parsing_start = time.perf_counter()

    try:
        messages = parse_messages(userMessage.messages)

    except Exception as exc:
        status_code, message = get_safe_error_message(exc)

        logger.warning(
            "Message parsing failed | operation_id=%s | "
            "error_type=%s",
            operation_id,
            type(exc).__name__,
        )

        return error_response(
            status_code,
            "INVALID_MESSAGES",
            message,
        )

    logger.info(
        "Messages parsed | operation_id=%s | duration=%.4fs",
        operation_id,
        time.perf_counter() - parsing_start,
    )

    fingerprint = create_fingerprint(userMessage, user_id)

    # ---------------------------------------------------------
    # 3. Check Redis availability.
    #
    # If Redis is unavailable, continue generation without
    # idempotency persistence. Do not fail the LLM request
    # solely because Redis is down.
    # ---------------------------------------------------------
    redis_available = False

    try:
        await redis_client.ping()
        redis_available = True

    except Exception:
        logger.exception(
            "Redis unavailable; proceeding without "
            "operation persistence | operation_id=%s",
            operation_id,
        )

    # ---------------------------------------------------------
    # 4. Claim the operation or handle an existing operation.
    # ---------------------------------------------------------
    if redis_available:
        operation_key = f"operation:{user_id}:{operation_id}"
        chunks_key = f"{operation_key}:chunks"

        try:
            claimed = await claim_operation(
                operation_id=operation_id,
                user_id=user_id,
                fingerprint=fingerprint,
            )

            logger.info(
                "Operation claim | operation_id=%s | claimed=%s",
                operation_id,
                claimed,
            )

            if not claimed:
                existing = await redis_client.hgetall(operation_key)

                if not existing:
                    return error_response(
                        409,
                        "OPERATION_STATE_MISSING",
                        "The operation record disappeared. "
                        "Use a new operation ID.",
                    )

                if existing.get("fingerprint") != fingerprint:
                    return error_response(
                        409,
                        "OPERATION_ID_CONFLICT",
                        "This operation ID belongs to a different request.",
                    )

                status = existing.get("status")

                # -------------------------------------------------
                # 4A. Replay a completed operation.
                # -------------------------------------------------
                if status == "COMPLETED":
                    saved_chunks = await redis_client.lrange(
                        chunks_key,
                        0,
                        -1,
                    )

                    if not saved_chunks:
                        return error_response(
                            409,
                            "EMPTY_COMPLETED_OPERATION",
                            "The completed operation has no stored response.",
                        )

                    async def replay_generator():
                        replay_start = time.perf_counter()

                        logger.info(
                            "Redis replay started | operation_id=%s | "
                            "stored_chunks=%d",
                            operation_id,
                            len(saved_chunks),
                        )

                        try:
                            first_event = True

                            for event in replay_batches(saved_chunks):
                                if first_event:
                                    logger.info(
                                        "Redis first replay event | "
                                        "operation_id=%s | duration=%.4fs",
                                        operation_id,
                                        time.perf_counter() - replay_start,
                                    )
                                    first_event = False

                                yield event

                            logger.info(
                                "Redis replay completed | operation_id=%s | "
                                "duration=%.4fs",
                                operation_id,
                                time.perf_counter() - replay_start,
                            )

                            yield encode_sse({"done": True})

                        except asyncio.CancelledError:
                            raise

                        except Exception:
                            logger.exception(
                                "Redis replay failed | operation_id=%s",
                                operation_id,
                            )

                            yield encode_sse({
                                "error": {
                                    "code": "REPLAY_FAILED",
                                    "message": (
                                        "Could not replay the stored response."
                                    ),
                                }
                            })

                    return StreamingResponse(
                        replay_generator(),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "X-Accel-Buffering": "no",
                        },
                    )

                # -------------------------------------------------
                # 4B. Attach to an operation already generating.
                # -------------------------------------------------
                if status == "RUNNING":

                    async def attach_to_existing_stream():
                        index = 0
                        attach_start = time.perf_counter()

                        logger.info(
                            "Attaching to running operation | "
                            "operation_id=%s",
                            operation_id,
                        )

                        while True:
                            chunks = await redis_client.lrange(
                                chunks_key,
                                index,
                                index + POLL_BATCH_SIZE - 1,
                            )

                            if chunks:
                                for event in replay_batches(chunks):
                                    yield event

                                index += len(chunks)

                            current_status = await redis_client.hget(
                                operation_key,
                                "status",
                            )

                            if current_status == "COMPLETED":
                                total_chunks = await redis_client.llen(
                                    chunks_key
                                )

                                if index >= total_chunks:
                                    logger.info(
                                        "Attached stream completed | "
                                        "operation_id=%s | duration=%.4fs",
                                        operation_id,
                                        time.perf_counter() - attach_start,
                                    )

                                    yield encode_sse({"done": True})
                                    return

                                continue

                            if current_status == "FAILED":
                                total_chunks = await redis_client.llen(
                                    chunks_key
                                )

                                if index < total_chunks:
                                    continue

                                yield encode_sse({
                                    "error": {
                                        "code": "OPERATION_FAILED",
                                        "message": (
                                            "The original generation failed."
                                        ),
                                    }
                                })
                                return

                            if current_status != "RUNNING":
                                yield encode_sse({
                                    "error": {
                                        "code": "OPERATION_STATE_UNKNOWN",
                                        "message": (
                                            "The operation is no longer "
                                            "in a recognized state."
                                        ),
                                    }
                                })
                                return

                            await asyncio.sleep(POLL_INTERVAL_SECONDS)

                    return StreamingResponse(
                        attach_to_existing_stream(),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "X-Accel-Buffering": "no",
                        },
                    )

                # -------------------------------------------------
                # 4C. Retry a previously failed operation.
                # -------------------------------------------------
                if status == "FAILED":
                    retry_claimed = await retry_failed_operation(
                        operation_id=operation_id,
                        user_id=user_id,
                    )

                    if not retry_claimed:
                        return error_response(
                            409,
                            "RETRY_CONFLICT",
                            "The failed operation cannot be restarted "
                            "safely. Use a new operation ID.",
                        )

                    logger.info(
                        "Failed operation reset to RUNNING | "
                        "operation_id=%s",
                        operation_id,
                    )

                else:
                    return error_response(
                        409,
                        "OPERATION_STATE_UNKNOWN",
                        "The operation has an unexpected state.",
                    )

        except Exception:
            logger.exception(
                "Could not safely inspect or claim operation | "
                "operation_id=%s",
                operation_id,
            )

            return error_response(
                503,
                "OPERATION_STORE_UNAVAILABLE",
                "Could not safely determine the operation state. "
                "Retry using the same operation ID.",
            )

    # ---------------------------------------------------------
    # 5. Initialize the LLM stream.
    #
    # Do not call iterator.__anext__() here.
    # We must not wait for Groq's first chunk before returning
    # StreamingResponse.
    # ---------------------------------------------------------
    try:
        provider = get_llm_registry().get_provider(
            userMessage.provider
        )

        llm = llmservice(provider)

        stream_start = time.perf_counter()

        logger.info(
            "LLM streaming initialized | operation_id=%s | "
            "provider=%s | model=%s",
            operation_id,
            userMessage.provider,
            userMessage.model,
        )

        stream = llm.generate(
            prompt=userMessage.prompt,
            messages=messages,
            model=userMessage.model,
        )

        iterator = stream.__aiter__()

    except Exception as exc:
        logger.exception(
            "Could not initialize LLM stream | operation_id=%s",
            operation_id,
        )

        if redis_available:
            try:
                await persist_failure(operation_id, user_id, exc)
            except Exception:
                logger.exception(
                    "Could not persist initialization failure | "
                    "operation_id=%s",
                    operation_id,
                )

        status_code, message = get_safe_error_message(exc)

        return error_response(
            status_code,
            "LLM_INITIALIZATION_FAILED",
            message,
        )

    # ---------------------------------------------------------
    # 6. Stream immediately and persist non-empty text in batches.
    # ---------------------------------------------------------
    async def event_generator():
        chunk_count = 0
        non_empty_text_seen = False
        pending_chunks: list[str] = []

        try:
            logger.info(
                "SSE stream started | operation_id=%s | "
                "initialization_duration=%.4fs",
                operation_id,
                time.perf_counter() - stream_start,
            )

            # This event is yielded before waiting for Groq output.
            yield encode_sse({"status": "started"})

            async for raw_chunk in iterator:
                chunk = get_chunk_text(raw_chunk)
                chunk_count += 1

                # Record the first provider event, including empty events.
                if chunk_count == 1:
                    logger.info(
                        "First provider chunk received | "
                        "operation_id=%s | content_empty=%s | "
                        "duration=%.4fs",
                        operation_id,
                        not bool(chunk),
                        time.perf_counter() - stream_start,
                    )

                if chunk:
                    non_empty_text_seen = True

                    if redis_available:
                        pending_chunks.append(chunk)

                # Forward every chunk, including empty text.
                # Do not wait for the first non-empty chunk.
                yield encode_sse({"text": chunk})

                # Persist after yielding the event to the ASGI server.
                if (
                    redis_available
                    and len(pending_chunks) >= REDIS_WRITE_BATCH_SIZE
                ):
                    await append_chunks(
                        operation_id,
                        user_id,
                        pending_chunks,
                    )

                    pending_chunks.clear()

            # The provider stream ended. An empty response is not success.
            if not non_empty_text_seen:
                exc = RuntimeError(
                    "The provider completed without returning text."
                )

                if redis_available:
                    await persist_failure(
                        operation_id,
                        user_id,
                        exc,
                    )

                yield encode_sse({
                    "error": {
                        "code": "EMPTY_LLM_RESPONSE",
                        "message": (
                            "The provider completed without returning text."
                        ),
                    }
                })
                return

            # Flush the final partial batch before marking completion.
            if redis_available and pending_chunks:
                await append_chunks(
                    operation_id,
                    user_id,
                    pending_chunks,
                )

                pending_chunks.clear()

            if redis_available:
                await complete_operation(
                    operation_id,
                    user_id,
                )

            logger.info(
                "Streaming completed | operation_id=%s | "
                "chunks=%d | duration=%.2fs",
                operation_id,
                chunk_count,
                time.perf_counter() - request_start,
            )

            yield encode_sse({"done": True})

        except asyncio.CancelledError:
            logger.info(
                "Client stream cancelled | operation_id=%s",
                operation_id,
            )

            if redis_available:
                try:
                    await persist_failure(
                        operation_id,
                        user_id,
                        RuntimeError(
                            "The streaming request was cancelled."
                        ),
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist cancellation | "
                        "operation_id=%s",
                        operation_id,
                    )

            raise

        except Exception as exc:
            logger.exception(
                "Streaming or Redis persistence failed | "
                "operation_id=%s | chunks=%d",
                operation_id,
                chunk_count,
            )

            if redis_available:
                try:
                    await persist_failure(
                        operation_id,
                        user_id,
                        exc,
                    )
                except Exception:
                    logger.exception(
                        "Failed to persist operation failure | "
                        "operation_id=%s",
                        operation_id,
                    )

            _, safe_message = get_safe_error_message(exc)

            yield encode_sse({
                "error": {
                    "code": "STREAMING_FAILED",
                    "message": safe_message,
                }
            })

        finally:
            # Release the provider iterator when the client disconnects
            # or the generator exits.
            close = getattr(iterator, "aclose", None)

            if close is not None:
                try:
                    await close()
                except Exception:
                    logger.debug(
                        "Provider iterator cleanup failed | "
                        "operation_id=%s",
                        operation_id,
                        exc_info=True,
                    )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )