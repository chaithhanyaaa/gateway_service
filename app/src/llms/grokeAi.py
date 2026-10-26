
import asyncio
import logging
import time

import httpx
from groq import APIConnectionError, APITimeoutError, APIStatusError
from langchain.messages import HumanMessage
from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq

from app.src.core.config import settings
from app.src.llms.circuit_breakers.groqbreaker import (
    groq_circuit_breaker,
)
from app.src.llms.llm import LLMContract
from app.src.util.utilservice import calculate_backoff

logger = logging.getLogger(__name__)

FIRST_CONTENT_TIMEOUT_SECONDS = 30.0
CHUNK_IDLE_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3

RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)


class FirstContentTimeoutError(TimeoutError):
    """No non-empty LLM content arrived within the allowed time."""


class ChunkIdleTimeoutError(TimeoutError):
    """No subsequent LLM chunk arrived within the allowed time."""


class GroqProvider(LLMContract):

    async def generate(
        self,
        prompt: str,
        messages: list[BaseMessage] | None = None,
        model: str | None = None,
    ):
        current_messages = list(messages) if messages is not None else []

        if prompt:
            current_messages.append(HumanMessage(content=prompt))

        permit = await groq_circuit_breaker.before_request()
        first_content_received = False

        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                llm = ChatGroq(
                    model=model,
                    temperature=0.0,
                    groq_api_key=settings.grokAPIKey,
                    timeout=FIRST_CONTENT_TIMEOUT_SECONDS,
                    streaming=True,
                    max_retries=0,
                )

                stream_start = time.perf_counter()
                raw_chunk_logged = False
                iterator = llm.astream(current_messages).__aiter__()

                try:
                    while True:
                        timeout_seconds = (
                            FIRST_CONTENT_TIMEOUT_SECONDS
                            if not first_content_received
                            else CHUNK_IDLE_TIMEOUT_SECONDS
                        )

                        try:
                            chunk = await asyncio.wait_for(
                                iterator.__anext__(),
                                timeout=timeout_seconds,
                            )
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError as exc:
                            if not first_content_received:
                                raise FirstContentTimeoutError(
                                    "Timed out waiting for first non-empty "
                                    "LLM content."
                                ) from exc

                            raise ChunkIdleTimeoutError(
                                "Timed out waiting for the next LLM chunk."
                            ) from exc

                        elapsed = time.perf_counter() - stream_start
                        content = chunk.content

                        if not raw_chunk_logged:
                            raw_chunk_logged = True
                            logger.info(
                                "Groq first raw chunk | model=%s | "
                                "duration=%.2fs | content_empty=%s",
                                model,
                                elapsed,
                                not bool(content),
                            )

                        if not content:
                            continue

                        if not first_content_received:
                            first_content_received = True
                            logger.info(
                                "Groq first non-empty content | "
                                "model=%s | duration=%.2fs",
                                model,
                                elapsed,
                            )

                        yield content

                    await groq_circuit_breaker.record_success(permit)
                    return

                except (
                    APIConnectionError,
                    APITimeoutError,
                    httpx.TimeoutException,
                    FirstContentTimeoutError,
                ) as exc:
                    if first_content_received or attempt == MAX_ATTEMPTS:
                        raise

                    logger.warning(
                        "Groq connection/first-content timeout; "
                        "retrying (%d/%d). error_type=%s",
                        attempt,
                        MAX_ATTEMPTS,
                        type(exc).__name__,
                    )

                    await asyncio.sleep(calculate_backoff(attempt))

                except APIStatusError as exc:
                    retryable = exc.status_code in RETRYABLE_STATUS_CODES

                    if (
                        not retryable
                        or first_content_received
                        or attempt == MAX_ATTEMPTS
                    ):
                        raise

                    logger.warning(
                        "Groq HTTP %d; retrying (%d/%d)",
                        exc.status_code,
                        attempt,
                        MAX_ATTEMPTS,
                    )

                    await asyncio.sleep(calculate_backoff(attempt))

                finally:
                    close = getattr(iterator, "aclose", None)
                    if close is not None:
                        try:
                            await close()
                        except Exception:
                            logger.debug(
                                "Error closing Groq stream iterator",
                                exc_info=True,
                            )

        except asyncio.CancelledError:
            await groq_circuit_breaker.abandon(permit)
            raise

        except Exception as exc:
            is_provider_failure = isinstance(
                exc,
                (
                    APIConnectionError,
                    APITimeoutError,
                    httpx.TimeoutException,
                    FirstContentTimeoutError,
                    ChunkIdleTimeoutError,
                ),
            ) or (
                isinstance(exc, APIStatusError)
                and exc.status_code in RETRYABLE_STATUS_CODES
            )

            if is_provider_failure:
                await groq_circuit_breaker.record_failure(permit)

            raise
