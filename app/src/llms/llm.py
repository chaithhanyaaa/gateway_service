from abc import ABC, abstractmethod


class LLMContract(ABC):

    @abstractmethod
    async def generate(self, prompt:str=None,messages:list=None,model:str=None):
        pass