import os

from langchain.messages import HumanMessage,AIMessage,SystemMessage
import logging
import asyncio
import httpx
from groq import APIConnectionError, APITimeoutError, APIStatusError
from langchain_core.messages import BaseMessage
from app.src.llms.circuit_breakers.groqbreaker import (
    groq_circuit_breaker,
    CircuitBreakerOpenError,
)
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

      # Check the breaker once for the entire generation operation.
      permit = await groq_circuit_breaker.before_request()

      max_attempts = 3
      first_content_received = False

      try:
          for attempt in range(1, max_attempts + 1):
              llm = ChatGroq(
                  model=model,
                  temperature=0.0,
                  groq_api_key=settings.grokAPIKey,
                  timeout=10.0,
                  streaming=True,
                  max_retries=0,
              )

              try:
                    
                    
                 
        
                
                  async for chunk in llm.astream(current_messages):
                      if chunk.content:
                          first_content_received = True
                          yield chunk.content

                  # Reached only after the stream finishes successfully.
                  await groq_circuit_breaker.record_success(permit)
                  return

              except (
                  APIConnectionError,
                  APITimeoutError,
                  httpx.TimeoutException,
              ) as exc:
                  if first_content_received or attempt == max_attempts:
                      raise

                  logger.warning(
                      "Groq connection/timeout failure; retrying "
                      "(%d/%d). Error type: %s",
                      attempt,
                      max_attempts,
                      type(exc).__name__,
                  )

                  await asyncio.sleep(calculate_backoff(attempt))

              except APIStatusError as exc:
                  retryable = exc.status_code in (429, 500, 502, 503, 504)

                  if not retryable or first_content_received:
                      raise

                  if attempt == max_attempts:
                      raise

                  logger.warning(
                      "Groq HTTP %d; retrying (%d/%d)",
                      exc.status_code,
                      attempt,
                      max_attempts,
                  )

                  await asyncio.sleep(calculate_backoff(attempt))

      except asyncio.CancelledError:
          # A disconnected client is not automatically a Groq failure.
          await groq_circuit_breaker.abandon(permit)
          raise

      except Exception as exc:
          # Count only failures that indicate provider unavailability.
          is_provider_failure = isinstance(
              exc,
              (APIConnectionError, APITimeoutError, httpx.TimeoutException),
          ) or (
              isinstance(exc, APIStatusError)
              and exc.status_code in (500, 502, 503, 504)
          )

          if is_provider_failure:
              await groq_circuit_breaker.record_failure(permit)

          raise
