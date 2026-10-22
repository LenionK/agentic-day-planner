"""Every sentence the planner writes for the user, in Italian and in English.

The graph and the API never write a sentence directly: they ask for a message by key, in the
language of the plan (say("save_new", "en")). All the texts are here, so a translation is one
place to change, and a test checks that every key has every language with the same
placeholders: a forgotten translation is a failing test, not a page in two languages.

Not here: the prompts and what the LLM writes (the critic's comment, task titles), which stay
in Italian, the language the prompts are written and evaluated in.
"""

from string import Formatter
from typing import Literal

Language = Literal["it", "en"]
LANGUAGES: tuple[Language, ...] = ("it", "en")

MESSAGES: dict[str, dict[Language, str]] = {
    # parser: orari tolti perché inventati o spostati sul task sbagliato
    "time_not_in_sentence": {
        "it": "{title}: ignorato {field} {value} (non compare nella frase)",
        "en": "{title}: {field} {value} ignored (not in the sentence)",
    },
    "time_in_other_task": {
        "it": "{title}: ignorato {field} {value} (compare solo in un altro task)",
        "en": "{title}: {field} {value} ignored (it belongs to another task)",
    },
    "start_equals_deadline": {
        "it": "{title}: ignorato earliest_start {value} (uguale alla scadenza)",
        "en": "{title}: earliest_start {value} ignored (same as the deadline)",
    },
    # editor: correzioni dell'utente non applicate
    "edit_unknown_task": {
        "it": "{task_id}: correzione ignorata (task inesistente)",
        "en": "{task_id}: edit ignored (no such task)",
    },
    "edit_invalid": {
        "it": "{task_id}: correzione ignorata ({error})",
        "en": "{task_id}: edit ignored ({error})",
    },
    "edit_saved_task": {
        "it": "{task_id}: task già in agenda, non modificabile",
        "en": "{task_id}: already in the saved plan, cannot be edited",
    },
    # critico: proposte che non entrano in nessun buco libero
    "suggestion_does_not_fit": {
        "it": "Proposta scartata: {title} ({minutes} min) non entra in nessun intervallo libero",
        "en": "Suggestion dropped: {title} ({minutes} min) does not fit in any free slot",
    },
    # salvataggio del piano
    "save_no_date": {
        "it": "Piano non salvato: manca la data.",
        "en": "Plan not saved: the date is missing.",
    },
    "save_conflict": {
        "it": "Piano non salvato: nel frattempo la data è stata salvata altrove.",
        "en": "Plan not saved: meanwhile the date was saved from somewhere else.",
    },
    "save_merged": {
        "it": "Piano unito a quello già salvato.",
        "en": "Plan merged into the one already saved.",
    },
    "save_replaced": {
        "it": "Piano salvato al posto di quello precedente.",
        "en": "Plan saved in place of the previous one.",
    },
    "save_new": {"it": "Piano salvato.", "en": "Plan saved."},
    "save_left_out": {
        "it": " Non salvati perché fuori dal piano: {titles}.",
        "en": " Not saved because left out of the plan: {titles}.",
    },
    # memoria delle preferenze
    "preferences_result": {"it": "Preferenze: {parts}.", "en": "Preferences: {parts}."},
    "preferences_saved": {"it": "ricordate {count}", "en": "{count} remembered"},
    "preferences_seen_again": {"it": "già note {count}", "en": "{count} already known"},
    "preferences_deleted": {"it": "cancellate {count}", "en": "{count} deleted"},
    # errori dell'API
    "plan_not_found": {"it": "Pianificazione inesistente.", "en": "No such plan."},
    "plan_finished": {
        "it": "Pianificazione già conclusa.",
        "en": "This plan is already finished.",
    },
    "database_unavailable": {
        "it": "Database non disponibile.",
        "en": "The database is not available.",
    },
    "database_down": {
        "it": "Database non raggiungibile.",
        "en": "The database does not answer.",
    },
    "no_saved_plan": {
        "it": "Nessun piano salvato per il {day}.",
        "en": "No plan saved for {day}.",
    },
    "preference_not_found": {"it": "Preferenza inesistente.", "en": "No such preference."},
}


def say(key: str, language: Language = "it", **values) -> str:
    """The message `key` in `language`, with its placeholders filled in."""
    return MESSAGES[key][language].format(**values)


def placeholders(template: str) -> set[str]:
    """The names between braces in a template: "{title} ({minutes} min)" -> {"title", "minutes"}."""
    return {name for _, name, _, _ in Formatter().parse(template) if name}
