from ollama import Client
from pydantic import BaseModel

from planner.llm.base import LLMClient


class OllamaClient(LLMClient):
    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        temperature: float = 0.0,
        num_ctx: int = 8192,
        max_retries: int = 2,
    ) -> None:
        super().__init__(max_retries)
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx
        self._client = Client(host=host)

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        response = self._client.chat(
            model=self.model,
            messages=messages,
            format=schema.model_json_schema(),
            options={"temperature": self.temperature, "num_ctx": self.num_ctx},
        )
        return response.message.content
