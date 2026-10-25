
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import random,json,hashlib
from app.src.DTO.UserMessage import UserMessage


def calculate_backoff(attempt: int,base_delay: float = 1.0,max_delay: float = 10.0,) -> float:
    exponential_delay = min(
        base_delay * (2 ** (attempt - 1)),
        max_delay,
    )

    # Add jitter: randomize the delay by +/- 20%.
    jittered_delay = exponential_delay * random.uniform(0.8, 1.2)
    return min(jittered_delay, max_delay)



def parse_messages(messages):
  parsed_messages=[]
  for msg in messages:
      if msg.get("role")=="user":
        parsed_messages.append(HumanMessage(content=msg.get("content")))
      elif msg.get("role")=="assistant":
        parsed_messages.append(AIMessage(content=msg.get("content")))
      elif msg.get("role")=="system":
        parsed_messages.append(SystemMessage(content=msg.get("content")))
  return parsed_messages




from groq import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
)
import httpx


def get_safe_error_message(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, (APITimeoutError, httpx.TimeoutException)):
        return 504, "The AI provider timed out. Please try again."

    if isinstance(exc, APIConnectionError):
        return 502, "Unable to connect to the AI provider. Please try again."

    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return 429, "The AI provider is busy. Please try again shortly."

        if exc.status_code in (500, 502, 503, 504):
            return 502, "The AI provider is temporarily unavailable."

        if exc.status_code in (401, 403):
            return 502, "The AI provider could not authorize the request."

        if exc.status_code == 400:
            return 400, "The AI provider rejected the request."

    return 502, "The AI request failed unexpectedly. Please try again."



def create_fingerprint(user_message: UserMessage, user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "prompt": user_message.prompt,
        "messages": user_message.messages,
        "provider": user_message.provider,
        "model": user_message.model,
    }

    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )

    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

