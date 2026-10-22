"""The language line at the end of the prompts: nothing in Italian, only some fields in English."""

import json

from planner.agents import critic, parser
from planner.agents.critic import critic_messages
from planner.agents.parser import parse_day
from planner.solver.models import DayConfig, Schedule, ScheduledTask
from tests.fakes import FakeClient

PLAN = Schedule(
    status="OPTIMAL",
    scheduled=[ScheduledTask(task_id="t1", title="Studio", start_min=480, end_min=600)],
)
ONE_TASK = json.dumps({"tasks": [{"source": "studio", "title": "Study", "duration_min": 60}]})


def system_prompt_of(client: FakeClient) -> str:
    return client.calls[0][0]["content"]


def test_italian_parser_prompt_is_the_measured_one():
    client = FakeClient([ONE_TASK])

    parse_day("studio", client, "it")

    assert system_prompt_of(client) == parser.SYSTEM_PROMPT  # quello misurato con run_eval.py


def test_english_parser_prompt_asks_english_titles_and_italian_sources():
    client = FakeClient([ONE_TASK])

    parse_day("studio", client, "en")

    prompt = system_prompt_of(client)
    assert prompt.startswith(parser.SYSTEM_PROMPT)
    ending = prompt.removeprefix(parser.SYSTEM_PROMPT)
    assert "title in inglese" in ending
    assert "source resta copiato parola per parola" in ending  # i controlli sugli orari lo usano


def test_italian_critic_prompt_is_the_measured_one():
    messages = critic_messages(PLAN, [], DayConfig(), language="it")

    assert messages[0]["content"] == critic.SYSTEM_PROMPT


def test_english_critic_prompt_keeps_preferences_and_categories_italian():
    messages = critic_messages(
        PLAN, [], DayConfig(), ["preferisce studiare la mattina"], None, "en"
    )

    ending = messages[0]["content"].removeprefix(critic.SYSTEM_PROMPT)
    assert "assessment" in ending and "inglese" in ending
    assert "applied_preferences e category restano" in ending
    # i dati del giorno non cambiano lingua: sono gli stessi in tutte e due
    assert (
        messages[1] == critic_messages(PLAN, [], DayConfig(), ["preferisce studiare la mattina"])[1]
    )
