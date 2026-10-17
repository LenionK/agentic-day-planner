from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from planner.agents.approval import PlanReviewResponse, approval, plan_summary
from planner.agents.editor import ApprovalResponse, apply_edits
from planner.agents.parser import parse_day
from planner.agents.state import PlannerState
from planner.llm.base import LLMClient
from planner.solver.cpsat_scheduler import schedule

# etichette restituite da route_after_review, collegate ai nodi nella mappa dell'arco
ACCEPT = "accept"
EDIT = "edit"


def all_warnings(state: PlannerState) -> list[str]:
    """Parser warnings plus the ones of the last round of edits (older rounds are outdated)."""
    return state["warnings"] + state.get("edit_warnings", [])


def route_after_review(state: PlannerState) -> str:
    """Choose where to go after the plan review. Reads the state, never changes it."""
    return ACCEPT if state["plan_accepted"] else EDIT


def build_graph(client: LLMClient, checkpointer=None):
    """Build the planner graph.

    START -> parser -> ask_approval -> editor -> scheduler -> review_plan
    review_plan -> END (plan accepted) or back to ask_approval (more edits).

    ask_approval and review_plan pause the graph until the user answers; the graph needs
    a checkpointer to resume. Each loop starts from the tasks already edited.

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

    def ask_approval(state: PlannerState) -> dict:
        # il riepilogo è ciò che il chiamante vede in result["__interrupt__"]
        summary = approval(state["tasks"], state["rejected"], all_warnings(state))
        # alla ripresa il nodo riparte dall'inizio e interrupt restituisce la risposta
        # response_schema: il chiamante vede lo schema, e una risposta non valida
        # solleva ValidationError lasciando il grafo in pausa (si può riprovare)
        answer = interrupt(summary, response_schema=ApprovalResponse)
        # nello stato solo dati semplici, e solo i campi scritti dall'utente
        return {"user_response": answer.model_dump(exclude_unset=True)}

    def editor_node(state: PlannerState) -> dict:
        response = ApprovalResponse.model_validate(state["user_response"])
        tasks, edit_warnings = apply_edits(state["tasks"], response)
        return {"tasks": tasks, "edit_warnings": edit_warnings}

    def scheduler_node(state: PlannerState) -> dict:
        return {"schedule": schedule(state["tasks"], state["day"])}

    def review_plan(state: PlannerState) -> dict:
        summary = plan_summary(state["schedule"], state["tasks"], all_warnings(state))
        answer = interrupt(summary, response_schema=PlanReviewResponse)
        return {"plan_accepted": answer.accept}

    builder = StateGraph(PlannerState)
    builder.add_node("parser", parser_node)
    builder.add_node("ask_approval", ask_approval)
    builder.add_node("editor", editor_node)
    builder.add_node("scheduler", scheduler_node)
    builder.add_node("review_plan", review_plan)

    builder.add_edge(START, "parser")
    builder.add_edge("parser", "ask_approval")
    builder.add_edge("ask_approval", "editor")
    builder.add_edge("editor", "scheduler")
    builder.add_edge("scheduler", "review_plan")
    # mappa esplicita: LangGraph conosce in anticipo le destinazioni e le controlla
    builder.add_conditional_edges(
        "review_plan", route_after_review, {ACCEPT: END, EDIT: "ask_approval"}
    )

    return builder.compile(checkpointer=checkpointer)
