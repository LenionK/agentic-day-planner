from pydantic import BaseModel

from planner.llm.langchain_client import LangChainOllamaClient
from planner.llm.ollama_client import OllamaClient


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


def test_langchain_client_reuses_the_model_for_the_same_schema():
    client = LangChainOllamaClient(model="qwen2.5:7b")

    assert client._llm_for(SchemaA) is client._llm_for(SchemaA)
    assert client._llm_for(SchemaA) is not client._llm_for(SchemaB)
