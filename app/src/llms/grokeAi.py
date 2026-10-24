from langchain.messages import HumanMessage,AIMessage,SystemMessage

from app.src.llms.llm import LLMContract
from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq
from app.core.config import settings


class GroqProvider(LLMContract):
 

  # Inside your llmservice class:
  async def generate(self, prompt: str, messages: list[BaseMessage] = None, model: str = None):
      current_messages = list(messages) if messages is not None else []
      
      if prompt:
          current_messages.append(HumanMessage(content=prompt))

      llm = ChatGroq(
          model=model,
          temperature=0.0,
          groq_api_key=settings.grokAPIKey
      )
      
      # Use astream instead of ainvoke to read the chunks sequentially
      async for chunk in llm.astream(current_messages):
          # LangChain's Groq chunks contain the text fragment inside `.content`
          if chunk.content:
              yield chunk.content
