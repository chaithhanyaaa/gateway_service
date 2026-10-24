import json, time
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, SystemMessage, HumanMessage

from app.src.DTO.UserMessage import UserMessage
from app.src.llms.registry import get_llm_registry
from app.src.service.llmservice import llmservice
from app.src.util.utilservice import parse_messages
from app.src.core.auth import get_current_user
from fastapi import Depends


import logging
from app.src.util.utilservice import get_safe_error_message

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/chat")
async def create_item(userMessage: UserMessage, user_id: str = Depends(get_current_user),):
    logger.info("0.Authenticated gateway request")
    logger.info(
    "Gateway request accepted",
    extra={"user_id": user_id},
)
    request_start=time.perf_counter()
    
    messages = parse_messages(userMessage.messages)
    
    provider = get_llm_registry().get_provider(userMessage.provider)

    logger.info(f"2.Provider selected :{userMessage.provider}{userMessage.model}")
    llm = llmservice(provider)

    # 1. Define an async generator to stream the chunks
    
    async def event_generator():
        stream_start = time.perf_counter()
        chunk_count = 0

        logger.info("3.LLM streaming started")

        try:
            async for chunk in llm.generate(
                prompt=userMessage.prompt,
                messages=messages,
                model=userMessage.model,
            ):
                chunk_count += 1
                if chunk_count ==1:
                    logger.info("4.First chunk received from llm,time taken: %.2fs", time.perf_counter() - stream_start)


                content = str(chunk)

                yield f"data: {json.dumps({'text': content})}\n\n"

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
            logger.exception("LLM streaming failed")
            status_code, message = get_safe_error_message(exc)


            
            yield f"data: {json.dumps({
                'error': {
                    'code': status_code,
                    'message': message,
                }
            })}\n\n"
            return
    # 2. Return the generator wrapped in a StreamingResponse with the text/event-stream media type
    return StreamingResponse(event_generator(), media_type="text/event-stream")
