from app.src.llms.geminiAi import GeminiProvider
from app.src.llms.grokeAi import GroqProvider

class LLMRegistry:
    def __init__(self):
        self._providers = {
            "gemini": GeminiProvider(),
            "groq": GroqProvider(),
        }

    def get_provider(self, name: str):
        print(name)
        if name.lower() not in self._providers:
            raise ValueError(f"Provider {name} not found in registry")
        print(f"Retrieved provider: {name}")
        return self._providers.get(name.lower())

registry=LLMRegistry()

def get_llm_registry():
    return registry