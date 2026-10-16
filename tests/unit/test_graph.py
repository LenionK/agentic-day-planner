import json

from planner.agents.graph import build_graph
from planner.solver.models import DayConfig
from tests.fakes import FakeClient


def llm_answer(*drafts: dict) -> str:
    return json.dumps({"tasks": [{"source": d["title"], **d} for d in drafts]})


def test_graph_parses_and_schedules():
    client = FakeClient(
        [
            llm_answer(
                {
                    "source": "devo studiare 2 ore",
                    "title": "Studio",
                    "duration_min": 120,
                    "priority": 5,
                },
                {
                    "source": "dentista alle 15",
                    "title": "Dentista",
                    "duration_min": 60,
                    "required": True,
                    "fixed_start": "15:00",
                },
            )
        ]
    )
    graph = build_graph(client)
    day = DayConfig(day_start_min=480, day_end_min=1080)

    final = graph.invoke({"user_input": "devo studiare 2 ore, dentista alle 15", "day": day})

    plan = {item.title: item for item in final["schedule"].scheduled}
    assert set(plan) == {"Studio", "Dentista"}
    assert plan["Dentista"].start_min == 900
    assert final["rejected"] == []
    assert final["warnings"] == []


def test_graph_keeps_parser_warnings_and_rejected_tasks():
    client = FakeClient(
        [
            llm_answer(
                {"title": "Giro in bici", "duration_min": 60, "earliest_start": "10:30"},
                {
                    "source": "cena alle 25",
                    "title": "Cena",
                    "duration_min": 60,
                    "fixed_start": "25:00",
                },
            )
        ]
    )
    graph = build_graph(client)
    day = DayConfig(day_start_min=480, day_end_min=1080)

    final = graph.invoke({"user_input": "magari un giro in bici, cena alle 25", "day": day})

    assert [item.title for item in final["schedule"].scheduled] == ["Giro in bici"]
    assert len(final["warnings"]) == 1
    assert [r.draft.title for r in final["rejected"]] == ["Cena"]
