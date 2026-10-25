from typing import List, Optional
from pydantic import BaseModel, Field
from uuid import UUID



class UserMessage(BaseModel):
    prompt: str = Field(..., description="The main prompt for the LLM.")
    provider: str = Field(..., examples=["groq", "gemini"])
    model: str = Field(..., examples=["llama3-8b-8192", "gemini-1.5-pro"])
    messages: List[dict] = Field(
        ...,
        description="The chat history containing system, human, or AI messages."
    )
    operation_id: UUID = Field(
          description="Unique ID used to identify and resume an LLM operation."
      )
