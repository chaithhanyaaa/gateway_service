from app.src.llms.registry import get_llm_registry
import asyncio
from fastapi import FastAPI
from app.src.routers.chatRouter import router as chat_router 


app=FastAPI()
app.include_router(chat_router)
async def main():
    llm = get_llm_registry().get_provider("groq")
    response=await llm.generate(prompt="Hello, how are you ?",messages=[],model="openai/gpt-oss-20b")
    print(response)
    

    
    
    



