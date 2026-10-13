import pytest
from pydantic import BaseModel, Field, ValidationError

from planner.llm.base import LLMClient


class Item(BaseModel):
    name: str
    qty: int = Field(gt=0)


class FakeClient(LLMClient):
    """Restituisce risposte preparate, una per chiamata, e registra i messaggi ricevuti."""

    def __init__(self, responses: list[str], max_retries: int = 2) -> None:
        super().__init__(max_retries)
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        self.calls.append(list(messages))
        return self.responses.pop(0)


MESSAGES = [{"role": "user", "content": "una mela"}]


def test_valid_answer_needs_one_call():
    client = FakeClient(['{"name": "mela", "qty": 1}'])

    result = client.generate(MESSAGES, Item)

    assert result == Item(name="mela", qty=1)
    assert len(client.calls) == 1


def test_invalid_answer_is_retried_with_the_error():
    client = FakeClient(
        [
            '{"name": "mela", "qty": 0}',  # non valida: qty deve essere > 0
            '{"name": "mela", "qty": 1}',
        ]
    )

    result = client.generate(MESSAGES, Item)

    assert result.qty == 1
    assert len(client.calls) == 2
    second_call = client.calls[1]
    assert second_call[-2] == {"role": "assistant", "content": '{"name": "mela", "qty": 0}'}
    assert second_call[-1]["role"] == "user"
    assert "qty" in second_call[-1]["content"]


def test_gives_up_after_max_retries():
    client = FakeClient(['{"name": "mela", "qty": 0}'] * 3, max_retries=2)

    with pytest.raises(ValidationError):
        client.generate(MESSAGES, Item)

    assert len(client.calls) == 3  # 1 tentativo + 2 retry


def test_original_messages_are_not_modified():
    client = FakeClient(['{"name": "mela", "qty": 0}', '{"name": "mela", "qty": 1}'])
    messages = [{"role": "user", "content": "una mela"}]

    client.generate(messages, Item)

    assert messages == [{"role": "user", "content": "una mela"}]
