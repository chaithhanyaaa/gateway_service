
import json
import time
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, JSONResponse

from app.src.DTO.UserMessage import UserMessage
from app.src.llms.registry import get_llm_registry
from app.src.service.llmservice import llmservice
from app.src.util.utilservice import parse_messages, get_safe_error_message
from app.src.core.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat")
async def create_item(
    userMessage: UserMessage,
    user_id: str = Depends(get_current_user),
):
    request_start = time.perf_counter()

    logger.info("0.Authenticated gateway request")
    logger.info("Gateway request accepted")

    messages = parse_messages(userMessage.messages)

    provider = get_llm_registry().get_provider(userMessage.provider)

    logger.info(
        "2.Provider selected: %s | model: %s",
        userMessage.provider,
        userMessage.model,
    )

    llm = llmservice(provider)
    stream_start = time.perf_counter()

    logger.info("3.LLM streaming started")

    # Start the upstream stream and fetch its first chunk
    # BEFORE committing the HTTP response status.
    stream = llm.generate(
        prompt=userMessage.prompt,
        messages=messages,
        model=userMessage.model,
    )

    iterator = stream.__aiter__()

    try:
        first_chunk = await iterator.__anext__()

    except StopAsyncIteration:
        # The provider returned an empty stream.
        logger.info("LLM stream completed without chunks")

        async def empty_generator():
            if False:
                yield ""

        return StreamingResponse(
            empty_generator(),
            media_type="text/event-stream",
        )

    except Exception as exc:
        logger.exception("LLM failed before the first chunk")

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

    # Reaching here means the upstream produced its first chunk.
    logger.info(
        "4.First chunk received from LLM | time taken: %.2fs",
        time.perf_counter() - stream_start,
    )

    async def event_generator():
        chunk_count = 0

        try:
            # Send the first chunk that was fetched above.
            chunk_count += 1
            yield f"data: {json.dumps({'text': str(first_chunk)})}\n\n"

            # Continue streaming the remaining chunks.
            async for chunk in iterator:
                chunk_count += 1
                yield f"data: {json.dumps({'text': str(chunk)})}\n\n"

            stream_duration = time.perf_counter() - stream_start
            request_duration = time.perf_counter() - request_start

            logger.info(
                "5.Streaming completed | chunks: %d | "
                "stream duration: %.2fs | total request duration: %.2fs",
                chunk_count,
                stream_duration,
                request_duration,
            )

        except Exception as exc:
            logger.exception("LLM streaming failed after response started")

            status_code, message = get_safe_error_message(exc)

            yield (
                f"data: {json.dumps({'error': {'code': status_code, 'message': message}})}\n\n"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
