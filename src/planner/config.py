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
    # misurato: il prompt più lungo (parser) legge ~860 token e ne scrive ~200; 4096 lascia
    # margine al ciclo di correzione, e sta in VRAM. Oltre il limite Ollama taglia in silenzio
    llm_num_ctx: int = 4096
    llm_temperature: float = 0.0
    llm_num_predict: int = 2048
    llm_repeat_penalty: float | None = None  # None = default di Ollama
    # layer del modello sulla GPU. None = decide Ollama, che stima con prudenza: su una GTX 1060
    # da 6 GB lasciava il 13-21% di qwen2.5:7b sulla CPU (11-16 token/s). 99 = tutti sulla GPU
    # (22-24 token/s), se la VRAM basta: forzarlo su una scheda troppo piccola fa fallire il caricamento
    llm_num_gpu: int | None = None
    # quanto i modelli restano in memoria dopo l'ultima chiamata (Ollama: 5 minuti). Ricaricare
    # qwen2.5:7b costa da 4 a 20 secondi: più a lungo resta, meno si aspetta tra un piano e l'altro
    llm_keep_alive: str = "30m"

    # Only if LLM_PROVIDER=groq (free tier)
    groq_api_key: SecretStr = SecretStr("")

    # Database
    database_url: str = "postgresql://planner:planner@localhost:5433/planner"

    # Calendario: il fuso degli orari esportati in .ics
    timezone: str = "Europe/Rome"
