

from langchain_core.messages import BaseMessage
from app.src.llms.llm import LLMContract
class llmservice:
  def __init__(self,llm:LLMContract):
    self.llmProvider=llm

  async def generate(self,prompt:str,messages:list[BaseMessage]=None,model:str=None):
     async for token in self.llmProvider.generate(prompt=prompt, messages=messages, model=model):
            yield token

