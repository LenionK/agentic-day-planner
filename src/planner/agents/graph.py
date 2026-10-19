from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from planner.agents.approval import (
    EXISTING_DAY,
    SUGGEST_ACTIVITIES,
    ExistingDayResponse,
    PlanReviewResponse,
    approval,
    conflict_summary,
    plan_summary,
    saved_day_summary,
)
from planner.agents.critic import SuggestionsResponse, critique
from planner.agents.editor import ApprovalResponse, apply_edits
from planner.agents.parser import parse_day
from planner.agents.state import PlannerState
from planner.db.repository import DayAlreadySaved, PlanRepository
from planner.llm.base import LLMClient
from planner.solver.cpsat_scheduler import schedule

# etichette delle funzioni di instradamento, collegate ai nodi nelle mappe degli archi
DONE = "done"
REVIEW = "review"
CONFLICT = "conflict"
ACCEPT = "accept"
EDIT = "edit"
SUGGEST = "suggest"
SAVE = "save"
ASK = "ask"
SKIP = "skip"
REPLACE = "replace"
KEEP = "keep"


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


def route_before_save(state: PlannerState) -> str:
    """Save directly a new date, ask first if the date is already saved."""
    if "day_date" not in state:
        return SKIP
    return ASK if state["existing_day"] else SAVE


def route_after_existing_day(state: PlannerState) -> str:
    return REPLACE if state["save_choice"] == "replace" else KEEP


def build_graph(client: LLMClient, checkpointer=None, repository: PlanRepository | None = None):
    """Build the planner graph.

    START -> parser -> ask_approval -> editor -> scheduler, then from the solver's result:
    - all tasks scheduled -> critic
    - some tasks left out -> review_plan -> critic (accepted) or back to ask_approval
    - required tasks in conflict -> resolve_conflict -> editor -> scheduler again
    critic -> (suggest_activities when the day looks too empty) -> saving, then END:
    - new date -> save_plan
    - date already saved -> ask_existing_day -> save_plan (replace) or END (keep)

    ask_approval, resolve_conflict, review_plan, suggest_activities and ask_existing_day
    pause the graph until the user answers; the graph needs a checkpointer to resume.
    Each loop starts from the tasks already edited.

    The LLM client and the plan repository are injected here and reach the nodes through
    a closure, so they never enter the state (which must stay serializable).
    Without a repository the plan is not saved.
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

    def check_saved_day(state: PlannerState) -> dict:
        # solo lettura: decide se serve chiedere all'utente prima di salvare
        if "day_date" not in state:
            return {"save_result": {"saved": False, "message": "Piano non salvato: manca la data."}}
        saved = repository.load(state["day_date"])
        return {"existing_day": None if saved is None else saved_day_summary(saved)}

    def ask_existing_day(state: PlannerState) -> dict:
        new_plan = plan_summary(state["schedule"], state["tasks"], all_warnings(state))
        answer = interrupt(
            {
                "step": EXISTING_DAY,
                "day_date": state["day_date"].isoformat(),
                "saved": state["existing_day"],
                "new": new_plan,
            },
            response_schema=ExistingDayResponse,
        )
        update = {"save_choice": answer.choice}
        if answer.choice == "keep":
            day = state["day_date"].strftime("%d/%m/%Y")
            message = f"Piano non salvato: resta quello già salvato per il {day}."
            update["save_result"] = {"saved": False, "message": message}
        return update

    def save_plan(state: PlannerState) -> dict:
        # l'unico nodo che scrive fuori dal grafo; nessun interrupt, quindi alla ripresa
        # di un'altra domanda non viene rieseguito e non salva due volte
        replace = state.get("save_choice") == "replace"
        try:
            day_id = repository.save(
                state["day_date"],
                state["user_input"],
                state["day"],
                state["tasks"],
                state["schedule"],
                state["sources"],
                replace=replace,
            )
        except DayAlreadySaved:
            message = "Piano non salvato: nel frattempo la data è stata salvata altrove."
            return {"save_result": {"saved": False, "message": message}}
        message = "Piano salvato al posto di quello precedente." if replace else "Piano salvato."
        return {"save_result": {"saved": True, "day_id": day_id, "message": message}}

    # senza archivio il grafo finisce dopo il Critico, come prima
    after_plan = "check_saved_day" if repository is not None else END

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
        "critic", route_after_critic, {DONE: after_plan, SUGGEST: "suggest_activities"}
    )
    builder.add_edge("suggest_activities", after_plan)

    if repository is not None:
        builder.add_node("check_saved_day", check_saved_day)
        builder.add_node("ask_existing_day", ask_existing_day)
        builder.add_node("save_plan", save_plan)
        builder.add_conditional_edges(
            "check_saved_day",
            route_before_save,
            {SAVE: "save_plan", ASK: "ask_existing_day", SKIP: END},
        )
        builder.add_conditional_edges(
            "ask_existing_day", route_after_existing_day, {REPLACE: "save_plan", KEEP: END}
        )
        builder.add_edge("save_plan", END)

    return builder.compile(checkpointer=checkpointer)
