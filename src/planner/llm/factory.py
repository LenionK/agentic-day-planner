from planner.config import Settings
from planner.llm.base import LLMClient
from planner.llm.embedder import Embedder
from planner.llm.langchain_client import LangChainOllamaClient
from planner.llm.ollama_client import OllamaClient
from planner.llm.ollama_embedder import OllamaEmbedder


def build_llm_client(settings: Settings) -> LLMClient:
    """Create the LLM client selected in the settings."""
    common = {
        "model": settings.llm_model,
        "host": settings.ollama_host,
        "temperature": settings.llm_temperature,
        "num_ctx": settings.llm_num_ctx,
        "num_predict": settings.llm_num_predict,
        "repeat_penalty": settings.llm_repeat_penalty,
        "num_gpu": settings.llm_num_gpu,
        "keep_alive": settings.llm_keep_alive,
    }

    if settings.llm_provider == "ollama":
        return OllamaClient(**common)

    if settings.llm_provider == "langchain_ollama":
        return LangChainOllamaClient(**common)

    if settings.llm_provider == "groq":
        raise NotImplementedError("Groq client not implemented yet")

    raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")


def build_embedder(settings: Settings) -> Embedder:
    """Create the embedder: the embedding model always runs on Ollama, whatever the LLM provider."""
    return OllamaEmbedder(
        model=settings.embed_model, host=settings.ollama_host, keep_alive=settings.llm_keep_alive
    )
