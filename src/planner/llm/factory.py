from planner.config import Settings
from planner.llm.base import LLMClient
from planner.llm.langchain_client import LangChainOllamaClient
from planner.llm.ollama_client import OllamaClient


def build_llm_client(settings: Settings) -> LLMClient:
    """Create the LLM client selected in the settings."""
    common = {
        "model": settings.llm_model,
        "host": settings.ollama_host,
        "temperature": settings.llm_temperature,
        "num_ctx": settings.llm_num_ctx,
        "num_predict": settings.llm_num_predict,
        "repeat_penalty": settings.llm_repeat_penalty,
    }

    if settings.llm_provider == "ollama":
        return OllamaClient(**common)

    if settings.llm_provider == "langchain_ollama":
        return LangChainOllamaClient(**common)

    if settings.llm_provider == "groq":
        raise NotImplementedError("Groq client not implemented yet")

    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
