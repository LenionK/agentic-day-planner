from planner.config import Settings
from planner.llm.base import LLMClient
from planner.llm.ollama_client import OllamaClient


def build_llm_client(settings: Settings) -> LLMClient:
    """Create the LLM client selected in the settings."""
    if settings.llm_provider == "ollama":
        return OllamaClient(
            model=settings.llm_model,
            host=settings.ollama_host,
            num_ctx=settings.llm_num_ctx,
        )

    if settings.llm_provider == "groq":
        raise NotImplementedError("Groq client not implemented yet")

    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
