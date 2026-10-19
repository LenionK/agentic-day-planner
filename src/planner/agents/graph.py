from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from planner.agents.approval import (
    SUGGEST_ACTIVITIES,
    PlanReviewResponse,
    approval,
    conflict_summary,
    plan_summary,
    saved_day_summary,
)
from planner.agents.critic import SuggestionsResponse, critique
from planner.agents.editor import ApprovalResponse, apply_edits
from planner.agents.merge import merge_with_saved, pin_for_solver
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


def build_graph(client: LLMClient, checkpointer=None, repository: PlanRepository | None = None):
    """Build the planner graph.

    START -> parser -> ask_approval -> editor -> scheduler, then from the solver's result:
    - all tasks scheduled -> critic
    - some tasks left out -> review_plan -> critic (accepted) or back to ask_approval
    - required tasks in conflict -> resolve_conflict -> editor -> scheduler again
    critic -> (suggest_activities when the day looks too empty) -> save_plan -> END.

    With a repository, check_saved_day runs right after the parser: if the date already
    has a saved plan, its tasks join the new ones, pinned at their times, and the user sees
    them in the confirmation. The user can replace the saved plan instead of merging.
    save_plan writes at the end, without further questions.

    ask_approval, resolve_conflict, review_plan and suggest_activities pause the graph
    until the user answers; the graph needs a checkpointer to resume. Each loop starts
    from the tasks already edited.

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

    def check_saved_day(state: PlannerState) -> dict:
        # solo lettura, subito dopo il parser: il resto del grafo lavora sulla giornata intera
        if "day_date" not in state:
            return {}
        saved = repository.load(state["day_date"])
        if saved is None:
            return {"saved_day": None}
        tasks, sources, info = merge_with_saved(saved, state["tasks"], state["sources"])
        return {"tasks": tasks, "sources": sources, "saved_day": info}

    def ask_approval(state: PlannerState) -> dict:
        # il riepilogo è ciò che il chiamante vede in result["__interrupt__"];
        # i task già in agenda non si correggono: si mostrano a parte
        saved = state.get("saved_day")
        locked = set(saved["task_ids"]) if saved else set()
        new_tasks = [task for task in state["tasks"] if task.id not in locked]
        summary = approval(new_tasks, state["rejected"], all_warnings(state))
        summary["saved_day"] = saved_day_summary(saved, state["tasks"]) if saved else None
        # alla ripresa il nodo riparte dall'inizio e interrupt restituisce la risposta
        # response_schema: il chiamante vede lo schema, e una risposta non valida
        # solleva ValidationError lasciando il grafo in pausa (si può riprovare)
        answer = interrupt(summary, response_schema=ApprovalResponse)
        # nello stato solo dati semplici, e solo i campi scritti dall'utente
        return {"user_response": answer.model_dump(exclude_unset=True)}

    def editor_node(state: PlannerState) -> dict:
        response = ApprovalResponse.model_validate(state["user_response"])
        saved = state.get("saved_day")
        locked = set(saved["task_ids"]) if saved else set()
        tasks, sources = state["tasks"], state["sources"]
        update = {}

        if response.replace_saved and saved and not saved["replaced"]:
            # sostituire: via i task della giornata salvata, che alla fine verrà sovrascritta
            tasks = [task for task in tasks if task.id not in locked]
            sources = {key: text for key, text in sources.items() if key not in locked}
            update["saved_day"] = {**saved, "replaced": True, "task_ids": [], "pinned": {}}
            update["sources"] = sources

        warnings = [
            f"{task_id}: task già in agenda, non modificabile"
            for task_id in response.edits
            if task_id in locked
        ]
        allowed = {key: edit for key, edit in response.edits.items() if key not in locked}
        tasks, edit_warnings = apply_edits(tasks, ApprovalResponse(edits=allowed))
        return {"tasks": tasks, "edit_warnings": warnings + edit_warnings} | update

    def scheduler_node(state: PlannerState) -> dict:
        # i task già in agenda restano dove sono: fissi e obbligatori, ma solo per il solver
        saved = state.get("saved_day")
        pinned = saved["pinned"] if saved else {}
        return {"schedule": schedule(pin_for_solver(state["tasks"], pinned), state["day"])}

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

    def save_plan(state: PlannerState) -> dict:
        # l'unico nodo che scrive fuori dal grafo; nessun interrupt, quindi alla ripresa
        # di un'altra domanda non viene rieseguito e non salva due volte
        if "day_date" not in state:
            return {"save_result": {"saved": False, "message": "Piano non salvato: manca la data."}}
        saved = state.get("saved_day")
        replace = saved is not None  # unita o sostituita, la giornata salvata viene riscritta
        merged = saved is not None and not saved["replaced"]
        # unendo, restano tutte e due le frasi
        user_input = (
            f"{saved['user_input']} · {state['user_input']}" if merged else state["user_input"]
        )
        try:
            day_id = repository.save(
                state["day_date"],
                user_input,
                state["day"],
                state["tasks"],
                state["schedule"],
                state["sources"],
                replace=replace,
            )
        except DayAlreadySaved:
            message = "Piano non salvato: nel frattempo la data è stata salvata altrove."
            return {"save_result": {"saved": False, "message": message}}
        if merged:
            message = "Piano unito a quello già salvato."
        elif replace:
            message = "Piano salvato al posto di quello precedente."
        else:
            message = "Piano salvato."
        return {"save_result": {"saved": True, "day_id": day_id, "message": message}}

    # senza archivio niente controllo né salvataggio: il grafo è quello di prima
    after_parser = "check_saved_day" if repository is not None else "ask_approval"
    after_plan = "save_plan" if repository is not None else END

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
    builder.add_edge("parser", after_parser)
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
        builder.add_node("save_plan", save_plan)
        builder.add_edge("check_saved_day", "ask_approval")
        builder.add_edge("save_plan", END)

    return builder.compile(checkpointer=checkpointer)
