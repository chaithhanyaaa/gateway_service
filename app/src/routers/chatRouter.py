import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, SystemMessage, HumanMessage

from app.src.DTO.UserMessage import UserMessage
from app.src.llms.registry import get_llm_registry
from app.src.service.llmservice import llmservice
from app.src.util.utilservice import parse_messages

router = APIRouter()

@router.post("/chat")
async def create_item(userMessage: UserMessage):
    
    messages = parse_messages(userMessage.messages)
    
    provider = get_llm_registry().get_provider(userMessage.provider)
    llm = llmservice(provider)

    # 1. Define an async generator to stream the chunks
    async def event_generator():
        try:
            # Assuming your llmservice has an async streaming method (e.g., generate_stream)
            # that wraps LangChain's underlying `.astream()` method.
            async for chunk in llm.generate(prompt=userMessage.prompt, messages=messages, model=userMessage.model):
                # Extract the text content from the LangChain chunk if it's a message/dict object
                # or just use it directly if your service already extracts the string.
                print(f"Chunk received: {chunk}")  # Debugging line to see the chunk content
                print("#"*50)
                content =str(chunk)
                
                # SSE standard requires format: "data: <your_payload>\n\n"
                # Wrapping in json.dumps handles special characters and formatting safely.
                yield f"data: {json.dumps({'text': content})}\n\n"
                
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    # 2. Return the generator wrapped in a StreamingResponse with the text/event-stream media type
    return StreamingResponse(event_generator(), media_type="text/event-stream")
