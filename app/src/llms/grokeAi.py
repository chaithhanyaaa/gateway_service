from langchain.messages import HumanMessage,AIMessage,SystemMessage
import logging
import asyncio
import httpx
from groq import APIConnectionError, APITimeoutError, APIStatusError
from langchain_core.messages import BaseMessage

from app.src.llms.llm import LLMContract
from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq
from app.src.util.utilservice import calculate_backoff
from app.src.core.config import settings
logger = logging.getLogger(__name__)



class GroqProvider(LLMContract):
 

  # Inside your llmservice class:
    
  async def generate(
      self,
      prompt: str,
      messages: list[BaseMessage] = None,
      model: str = None,
  ):
      current_messages = list(messages) if messages is not None else []

      if prompt:
          current_messages.append(HumanMessage(content=prompt))

      max_attempts = 3

      for attempt in range(1, max_attempts + 1):
          llm = ChatGroq(
              model=model,
              temperature=0.0,
              groq_api_key=settings.grokAPIKey,
              timeout=10.0,
              streaming=True,
              max_retries=0,
          )

          first_content_received = False

          try:
              async for chunk in llm.astream(current_messages):
                  if chunk.content:
                      first_content_received = True
                      yield chunk.content

              return

          
          except (
              APIConnectionError,
              APITimeoutError,
              httpx.TimeoutException,
          ) as exc:
              if first_content_received:
                  logger.exception(
                      "Provider connection/timeout failure after "
                      "streaming started; cannot safely retry"
                  )
                  raise

              if attempt == max_attempts:
                  logger.exception(
                      "Provider connection/timeout failure; "
                      "all %d attempts exhausted",
                      max_attempts,
                  )
                  raise

              backoff_time = calculate_backoff(attempt)

              logger.warning(
                  "Provider connection/timeout failure before "
                  "first chunk; retrying (%d/%d). Error type: %s",
                  attempt,
                  max_attempts,
                  type(exc).__name__,
              )
              await asyncio.sleep(backoff_time)
              

          except APIStatusError as exc:
              retryable = exc.status_code in (429, 500, 502, 503, 504)

              if not retryable:
                  logger.error(
                      "Non-retryable provider HTTP error: status=%d",
                      exc.status_code,
                  )
                  raise

              if first_content_received:
                  logger.error(
                      "Retryable HTTP status %d occurred after "
                      "streaming started; cannot safely retry",
                      exc.status_code,
                  )
                  raise

              if attempt == max_attempts:
                  logger.error(
                      "Provider HTTP error %d; all %d attempts exhausted",
                      exc.status_code,
                      max_attempts,
                  )
                  raise

              logger.warning(
                  "Retryable provider HTTP error %d; retrying (%d/%d)",
                  exc.status_code,
                  attempt,
                  max_attempts,
              )
