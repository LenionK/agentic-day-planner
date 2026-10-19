from datetime import date
from typing import NotRequired, TypedDict

from planner.agents.parser import RejectedTask
from planner.solver.models import DayConfig, Schedule, Task


class PlannerState(TypedDict):
    """State shared by the planner graph nodes.

    The caller provides `user_input`, `day` and, to save the plan, `day_date`;
    every other field is written by a node.
    """

    # input
    user_input: str
    day: DayConfig
    day_date: NotRequired[date]  # senza data il piano non viene salvato

    # scritti dal Parser
    tasks: NotRequired[list[Task]]
    rejected: NotRequired[list[RejectedTask]]
    warnings: NotRequired[list[str]]
    sources: NotRequired[dict[str, str]]

    # scritto dalla conferma: la risposta dell'utente alla ripresa
    user_response: NotRequired[dict]

    # scritto dall'editor: solo gli avvisi dell'ultimo giro di correzioni
    edit_warnings: NotRequired[list[str]]

    # scritto dallo scheduler
    schedule: NotRequired[Schedule]

    # scritto dalla revisione del piano: True = accettato, False = torna alle correzioni
    plan_accepted: NotRequired[bool]

    # scritto dal Critico: valutazione della giornata e proposte valide, dati JSON semplici
    critique: NotRequired[dict]

    # scritto da check_saved_day (e dall'editor, se l'utente sceglie di sostituire):
    # la giornata già salvata per la data, i suoi task (non modificabili) e dove sono bloccati
    saved_day: NotRequired[dict | None]

    # scritto da save_plan: esito per il chiamante, salvato? e messaggio
    save_result: NotRequired[dict]

    # memoria delle preferenze, dopo il salvataggio
    preference_candidates: NotRequired[list[dict]]  # estratte, con duplicate e simili
    preference_answer: NotRequired[dict]  # risposta dell'utente: quali tenere e cancellare
    preference_result: NotRequired[dict]  # quante ricordate, già note, cancellate
