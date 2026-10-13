from pydantic import BaseModel

from planner.llm.base import LLMClient


class FakeClient(LLMClient):
    """Returns prepared answers, one per call, and records the messages it receives."""

    def __init__(self, responses: list[str], max_retries: int = 2) -> None:
        super().__init__(max_retries)
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        self.calls.append(list(messages))
        return self.responses.pop(0)
