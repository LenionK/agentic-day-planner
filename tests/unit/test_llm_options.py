from types import SimpleNamespace

from pydantic import BaseModel

from planner.llm.embedder import EMBED_DIM
from planner.llm.langchain_client import LangChainOllamaClient
from planner.llm.ollama_client import OllamaClient
from planner.llm.ollama_embedder import OllamaEmbedder


class SchemaA(BaseModel):
    a: int


class SchemaB(BaseModel):
    b: int


def test_ollama_options_leave_repeat_penalty_to_ollama_by_default():
    client = OllamaClient(model="qwen2.5:7b")

    assert "repeat_penalty" not in client._options()


def test_ollama_options_include_repeat_penalty_when_set():
    client = OllamaClient(model="qwen2.5:7b", repeat_penalty=1.3)

    assert client._options()["repeat_penalty"] == 1.3


def test_ollama_options_leave_the_gpu_layers_to_ollama_by_default():
    client = OllamaClient(model="qwen2.5:7b")

    assert "num_gpu" not in client._options()


def test_ollama_options_force_the_gpu_layers_when_set():
    client = OllamaClient(model="qwen2.5:7b", num_gpu=99)

    assert client._options()["num_gpu"] == 99


class RecordingClient:
    """Stands in for ollama.Client: records the arguments of every call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))

    def embed(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(embeddings=[[1.0] + [0.0] * (EMBED_DIM - 1)])


def test_ollama_client_sends_keep_alive_and_gpu_layers():
    client = OllamaClient(model="qwen2.5:7b", num_gpu=99, keep_alive="45m")
    client._client = RecordingClient()

    client.generate([{"role": "user", "content": "x"}], SchemaA)

    (call,) = client._client.calls
    assert call["keep_alive"] == "45m"
    assert call["options"]["num_gpu"] == 99


def test_embedder_sends_keep_alive():
    embedder = OllamaEmbedder(model="nomic-embed-text", keep_alive="45m")
    embedder._client = RecordingClient()

    embedder.embed(["preferisce studiare la mattina"], "document")

    assert embedder._client.calls[0]["keep_alive"] == "45m"


def test_langchain_client_passes_gpu_layers_and_keep_alive():
    llm = LangChainOllamaClient(model="qwen2.5:7b", num_gpu=99, keep_alive="45m")._llm_for(SchemaA)

    assert (llm.num_gpu, llm.keep_alive) == (99, "45m")


def test_langchain_client_reuses_the_model_for_the_same_schema():
    client = LangChainOllamaClient(model="qwen2.5:7b")

    assert client._llm_for(SchemaA) is client._llm_for(SchemaA)
    assert client._llm_for(SchemaA) is not client._llm_for(SchemaB)
