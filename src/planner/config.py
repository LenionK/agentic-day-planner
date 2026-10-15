from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    llm_provider: Literal["ollama", "langchain_ollama", "groq"] = "ollama"
    llm_model: str = "qwen2.5:7b"
    embed_model: str = "nomic-embed-text"
    ollama_host: str = "http://localhost:11434"
    llm_num_ctx: int = 8192
    llm_temperature: float = 0.0
    llm_num_predict: int = 2048
    llm_repeat_penalty: float | None = None  # None = default di Ollama

    # Only if LLM_PROVIDER=groq (free tier)
    groq_api_key: SecretStr = SecretStr("")

    # Database
    database_url: str = "postgresql://planner:planner@localhost:5433/planner"
