from ollama import Client
from pydantic import BaseModel

from planner.llm.base import LLMClient


class OllamaClient(LLMClient):
    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        temperature: float = 0.0,
        num_ctx: int = 4096,
        num_predict: int = 2048,
        repeat_penalty: float | None = None,
        num_gpu: int | None = None,
        keep_alive: str | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(max_retries)
        self.model = model
        self.host = host
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.repeat_penalty = repeat_penalty
        self.num_gpu = num_gpu
        self.keep_alive = keep_alive
        self._client = Client(host=host)

    def _options(self) -> dict:
        """Generation options sent to Ollama; unset values are left to Ollama's defaults."""
        options = {
            "temperature": self.temperature,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
        }
        if self.repeat_penalty is not None:
            options["repeat_penalty"] = self.repeat_penalty
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu  # layer sulla GPU: senza, li stima Ollama
        return options

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        response = self._client.chat(
            model=self.model,
            messages=messages,
            format=schema.model_json_schema(),
            options=self._options(),
            keep_alive=self.keep_alive,  # None: il default di Ollama (5 minuti)
        )
        return response.message.content
