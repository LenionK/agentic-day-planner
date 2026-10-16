from langgraph.graph import END, START, StateGraph

from planner.agents.parser import parse_day
from planner.agents.state import PlannerState
from planner.llm.base import LLMClient
from planner.solver.cpsat_scheduler import schedule


def build_graph(client: LLMClient, checkpointer=None):
    """Build the planner graph: START -> parser -> scheduler -> END.

    The LLM client is injected here and reaches the parser node through a closure,
    so it never enters the state (which must stay serializable).
    """

    def parser_node(state: PlannerState) -> dict:
        result = parse_day(state["user_input"], client)
        return {
            "tasks": result.tasks,
            "rejected": result.rejected,
            "warnings": result.warnings,
            "sources": result.sources,
        }

    def scheduler_node(state: PlannerState) -> dict:
        return {"schedule": schedule(state["tasks"], state["day"])}

    builder = StateGraph(PlannerState)
    builder.add_node("parser", parser_node)
    builder.add_node("scheduler", scheduler_node)

    builder.add_edge(START, "parser")
    builder.add_edge("parser", "scheduler")
    builder.add_edge("scheduler", END)

    return builder.compile(checkpointer=checkpointer)
