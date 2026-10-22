import pytest

from planner.config import Settings
from planner.llm.factory import build_llm_client
from planner.llm.langchain_client import LangChainOllamaClient
from planner.llm.ollama_client import OllamaClient


def custom_settings(provider: str) -> Settings:
    """Settings with values different from every default, so a lost value is detected."""
    return Settings(
        _env_file=None,
        llm_provider=provider,
        llm_model="phi4-mini:3.8b",
        ollama_host="http://ollama-test:11434",
        llm_num_ctx=6144,
        llm_temperature=0.5,
        llm_num_predict=512,
        llm_repeat_penalty=1.3,
        llm_num_gpu=99,
        llm_keep_alive="45m",
    )


@pytest.mark.parametrize(
    ("provider", "expected_class"),
    [("ollama", OllamaClient), ("langchain_ollama", LangChainOllamaClient)],
)
def test_builds_client_with_all_settings(provider, expected_class):
    client = build_llm_client(custom_settings(provider))

    assert isinstance(client, expected_class)
    assert client.model == "phi4-mini:3.8b"
    assert client.host == "http://ollama-test:11434"
    assert client.num_ctx == 6144
    assert client.temperature == 0.5
    assert client.num_predict == 512
    assert client.repeat_penalty == 1.3
    assert client.num_gpu == 99
    assert client.keep_alive == "45m"


def test_defaults_leave_gpu_layers_to_ollama_and_keep_models_loaded():
    client = build_llm_client(Settings(_env_file=None))

    assert client.num_gpu is None  # su una scheda piccola forzarlo farebbe fallire il caricamento
    assert client.keep_alive == "30m"
    assert client.num_ctx == 4096


def test_groq_is_not_implemented_yet():
    settings = Settings(_env_file=None, llm_provider="groq")

    with pytest.raises(NotImplementedError):
        build_llm_client(settings)
