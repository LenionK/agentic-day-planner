from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from planner.agents.approval import (
    SUGGEST_ACTIVITIES,
    PlanReviewResponse,
    approval,
    conflict_summary,
    plan_summary,
)
from planner.agents.critic import SuggestionsResponse, critique
from planner.agents.editor import ApprovalResponse, apply_edits
from planner.agents.parser import parse_day
from planner.agents.state import PlannerState
from planner.llm.base import LLMClient
from planner.solver.cpsat_scheduler import schedule

# etichette delle funzioni di instradamento, collegate ai nodi nelle mappe degli archi
DONE = "done"
REVIEW = "review"
CONFLICT = "conflict"
ACCEPT = "accept"
EDIT = "edit"
SUGGEST = "suggest"


def all_warnings(state: PlannerState) -> list[str]:
    """Parser warnings plus the ones of the last round of edits (older rounds are outdated)."""
    return state["warnings"] + state.get("edit_warnings", [])


def route_after_schedule(state: PlannerState) -> str:
    """Choose where to go after the scheduler, from the solver's result alone.

    The user already confirmed the tasks, so a plan with all of them needs no question:
    ask only when the plan differs from what was confirmed.
    """
    plan = state["schedule"]
    if plan.conflicts:
        return CONFLICT  # obbligatori incompatibili: va risolto, non si può accettare
    if plan.unscheduled:
        return REVIEW  # qualche task non entra: l'utente deve saperlo e decidere
    return DONE


def route_after_review(state: PlannerState) -> str:
    """Choose where to go after the plan review. Reads the state, never changes it."""
    return ACCEPT if state["plan_accepted"] else EDIT


def route_after_critic(state: PlannerState) -> str:
    """Ask the user only if the critic found the day too empty and has valid suggestions."""
    return SUGGEST if state["critique"]["suggestions"] else DONE


def build_graph(client: LLMClient, checkpointer=None):
    """Build the planner graph.

    START -> parser -> ask_approval -> editor -> scheduler, then from the solver's result:
    - all tasks scheduled -> critic
    - some tasks left out -> review_plan -> critic (accepted) or back to ask_approval
    - required tasks in conflict -> resolve_conflict -> editor -> scheduler again
    critic -> END, or suggest_activities -> END when the day looks too empty.

    ask_approval, resolve_conflict, review_plan and suggest_activities pause the graph until
    the user answers; the graph needs a checkpointer to resume. Each loop starts from the
    tasks already edited.

    The LLM client is injected here and reaches the parser and critic nodes through
    a closure, so it never enters the state (which must stay serializable).
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

    def resolve_conflict(state: PlannerState) -> dict:
        summary = conflict_summary(state["schedule"], state["tasks"], all_warnings(state))
        # stesso formato e stesso campo della conferma: l'editor applica la risposta
        # senza sapere da quale domanda arriva
        answer = interrupt(summary, response_schema=ApprovalResponse)
        return {"user_response": answer.model_dump(exclude_unset=True)}

    def review_plan(state: PlannerState) -> dict:
        summary = plan_summary(state["schedule"], state["tasks"], all_warnings(state))
        answer = interrupt(summary, response_schema=PlanReviewResponse)
        return {"plan_accepted": answer.accept}

    def critic_node(state: PlannerState) -> dict:
        # la chiamata all'LLM sta in un nodo senza interrupt: alla ripresa un nodo riparte
        # dall'inizio, e con l'interrupt qui rifarebbe la chiamata (lenta, e forse diversa)
        return {"critique": critique(state["schedule"], state["day"], client)}

    def suggest_activities(state: PlannerState) -> dict:
        # risposta sempre con un campo: Command(resume={}) non riprende il grafo
        # (un dict vuoto è letto come "nessuna risposta per nessun interrupt")
        # il piano viaggia con la critica: il chiamante vede solo il valore dell'interrupt,
        # e senza il piano l'utente leggerebbe un commento su qualcosa che non vede
        plan = plan_summary(state["schedule"], state["tasks"], all_warnings(state))
        interrupt(
            {"step": SUGGEST_ACTIVITIES, **state["critique"], "plan": plan},
            response_schema=SuggestionsResponse,
        )
        # TODO passo 3: le proposte accettate diventano task e tornano allo scheduler
        return {}

    builder = StateGraph(PlannerState)
    builder.add_node("parser", parser_node)
    builder.add_node("ask_approval", ask_approval)
    builder.add_node("editor", editor_node)
    builder.add_node("scheduler", scheduler_node)
    builder.add_node("resolve_conflict", resolve_conflict)
    builder.add_node("review_plan", review_plan)
    builder.add_node("critic", critic_node)
    builder.add_node("suggest_activities", suggest_activities)

    builder.add_edge(START, "parser")
    builder.add_edge("parser", "ask_approval")
    builder.add_edge("ask_approval", "editor")
    builder.add_edge("editor", "scheduler")
    # mappe esplicite: LangGraph conosce in anticipo le destinazioni e le controlla
    builder.add_conditional_edges(
        "scheduler",
        route_after_schedule,
        {DONE: "critic", REVIEW: "review_plan", CONFLICT: "resolve_conflict"},
    )
    builder.add_edge("resolve_conflict", "editor")
    builder.add_conditional_edges(
        "review_plan", route_after_review, {ACCEPT: "critic", EDIT: "ask_approval"}
    )
    builder.add_conditional_edges(
        "critic", route_after_critic, {DONE: END, SUGGEST: "suggest_activities"}
    )
    builder.add_edge("suggest_activities", END)

    return builder.compile(checkpointer=checkpointer)
