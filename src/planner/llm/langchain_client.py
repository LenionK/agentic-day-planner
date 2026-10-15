from langchain_ollama import ChatOllama
from pydantic import BaseModel

from planner.llm.base import LLMClient


class LangChainOllamaClient(LLMClient):
    """LLM client backed by LangChain's ChatOllama.

    Behaves like OllamaClient: it returns the raw text and leaves validation
    and retries to LLMClient.generate.
    """

    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        temperature: float = 0.0,
        num_ctx: int = 8192,
        num_predict: int = 2048,
        repeat_penalty: float | None = None,
        max_retries: int = 2,
    ) -> None:
        super().__init__(max_retries)
        self.model = model
        self.host = host
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.repeat_penalty = repeat_penalty
        self._llms: dict[type[BaseModel], ChatOllama] = {}

    def _llm_for(self, schema: type[BaseModel]) -> ChatOllama:
        """Return the ChatOllama configured for `schema`, creating it only the first time."""
        if schema not in self._llms:
            self._llms[schema] = ChatOllama(
                model=self.model,
                base_url=self.host,
                temperature=self.temperature,
                num_ctx=self.num_ctx,
                num_predict=self.num_predict,
                repeat_penalty=self.repeat_penalty,
                format=schema.model_json_schema(),
            )
        return self._llms[schema]

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        response = self._llm_for(schema).invoke(messages)
        return response.content
