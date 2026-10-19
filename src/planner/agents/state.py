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

    # scritti dal salvataggio
    existing_day: NotRequired[dict | None]  # il piano già salvato per la data, se c'è
    save_choice: NotRequired[str]  # "replace" o "keep", se la data esisteva
    save_result: NotRequired[dict]  # esito per il chiamante: salvato?, messaggio
