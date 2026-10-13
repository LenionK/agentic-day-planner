import pytest

from planner.config import Settings
from planner.llm.factory import build_llm_client
from planner.llm.ollama_client import OllamaClient


def test_builds_ollama_client_from_settings():
    settings = Settings(_env_file=None, llm_provider="ollama", llm_model="phi4-mini:3.8b")

    client = build_llm_client(settings)

    assert isinstance(client, OllamaClient)
    assert client.model == "phi4-mini:3.8b"


def test_groq_is_not_implemented_yet():
    settings = Settings(_env_file=None, llm_provider="groq")

    with pytest.raises(NotImplementedError):
        build_llm_client(settings)
