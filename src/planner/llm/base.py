from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError


class LLMClient(ABC):
    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    @abstractmethod
    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        """Send messages to the LLM and return the raw text of its answer."""

    def generate(self, messages: list[dict], schema: type[BaseModel]) -> BaseModel:
        history = list(messages)
        for attempt in range(self.max_retries + 1):
            raw = self._complete(history, schema)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as err:
                if attempt == self.max_retries:
                    raise
                history.append({"role": "assistant", "content": raw})
                history.append(
                    {
                        "role": "user",
                        "content": f"La risposta non è valida:\n{err}\nCorreggila rispettando lo schema.",
                    }
                )
