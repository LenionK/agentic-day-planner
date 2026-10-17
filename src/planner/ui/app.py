"""Streamlit interface: a caller of the planner graph, like the tests.

Run with: python -m streamlit run src/planner/ui/app.py
"""

import os

# prima di importare langgraph: checkpoint in modalità strict, come nei test
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

import uuid

import pandas as pd
import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from planner.agents.approval import CONFIRM_TASKS, REVIEW_PLAN, approval, plan_summary
from planner.agents.graph import all_warnings, build_graph
from planner.config import Settings
from planner.llm.factory import build_llm_client
from planner.solver.models import DayConfig
from planner.ui.edits import diff_edits, to_time

# colonne della tabella: nomi interni (quelli del riepilogo) -> come appaiono all'utente
COLUMNS = {
    "title": st.column_config.TextColumn("Titolo"),
    "duration_min": st.column_config.NumberColumn(
        "Durata (min)", min_value=1, max_value=720, step=1, required=True
    ),
    "priority": st.column_config.SelectboxColumn(
        "Priorità", options=[1, 2, 3, 4, 5], required=True
    ),
    "required": st.column_config.CheckboxColumn("Obbligatorio"),
    # selettore d'orario: l'utente non può scrivere un formato sbagliato; cella vuota = nessun vincolo
    "fixed_start": st.column_config.TimeColumn("Inizio", format="HH:mm", step=60),
    "earliest_start": st.column_config.TimeColumn("Dopo le", format="HH:mm", step=60),
    "deadline": st.column_config.TimeColumn("Entro le", format="HH:mm", step=60),
}
READ_ONLY = ["title"]
TIME_FIELDS = ("fixed_start", "earliest_start", "deadline")


@st.cache_resource
def get_graph():
    """Created once per server: a new InMemorySaver would forget the paused graphs."""
    client = build_llm_client(Settings())
    return build_graph(client, checkpointer=InMemorySaver())


def graph_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def remember(result: dict) -> None:
    """Store where the graph is: waiting for an answer (pending) or finished (final)."""
    if "__interrupt__" in result:
        (interrupt_,) = result["__interrupt__"]
        st.session_state.pending = interrupt_.value
        if interrupt_.value["step"] == CONFIRM_TASKS:
            st.session_state.round += 1  # giro nuovo -> tabella nuova (vedi key del data_editor)
    else:
        st.session_state.pop("pending", None)
        st.session_state.final = result


def start_planning(text: str) -> None:
    """Run the graph until its first question."""
    st.session_state.thread_id = str(uuid.uuid4())  # una conversazione nuova per ogni frase
    st.session_state.round = 0
    st.session_state.pop("final", None)
    remember(get_graph().invoke({"user_input": text, "day": DayConfig()}, graph_config()))


def answer(response: dict, error_prefix: str) -> None:
    """Resume the graph with the user's answer, then show the next screen.

    An invalid answer raises ValidationError inside the graph, which stays paused:
    the error is shown and the user can try again.
    """
    try:
        with st.spinner("Sto pianificando..."):
            result = get_graph().invoke(Command(resume=response), graph_config())
    except ValidationError as err:
        st.error(f"{error_prefix}: {short_errors(err)}")
        return
    remember(result)
    st.rerun()  # riparte lo script e mostra la schermata successiva


def tasks_table(tasks: list[dict]) -> pd.DataFrame:
    """Summary tasks as a table indexed by id, so each row keeps its task id."""
    # "HH:MM" -> time prima di creare la tabella: pandas trasformerebbe i None in NaN
    rows = [{**t, **{field: to_time(t[field]) for field in TIME_FIELDS}} for t in tasks]
    return pd.DataFrame(rows).set_index("id")[list(COLUMNS)]


def show_rejected(summary: dict) -> None:
    for rejected in summary["rejected"]:
        st.error(f"Scartato: {rejected['title']} ({rejected['reason']})")


def show_warnings(summary: dict) -> None:
    for warning in summary["warnings"]:
        st.warning(warning)


def short_errors(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in err.errors())


def show_confirmation(summary: dict) -> None:
    st.subheader("Controlla i task")
    if summary["tasks"]:
        st.caption(
            "Puoi cambiare durata, priorità, obbligo e orari prima di pianificare. "
            "Svuota un orario per togliere il vincolo."
        )
        edited = st.data_editor(
            tasks_table(summary["tasks"]),
            column_config=COLUMNS,
            disabled=READ_ONLY,
            hide_index=True,
            # una tabella nuova per ogni frase e per ogni giro di correzioni
            key=f"editor-{st.session_state.thread_id}-{st.session_state.round}",
        )
    else:
        st.info("Nessun task riconosciuto nella frase.")
        edited = pd.DataFrame()
    show_rejected(summary)
    show_warnings(summary)

    # bottoni affiancati e allineati a destra (st.columns li allargherebbe a metà pagina)
    buttons = st.container(horizontal=True, horizontal_alignment="right")
    if buttons.button("Conferma e pianifica", type="primary"):
        answer(diff_edits(summary["tasks"], edited.to_dict("index")), "Correzioni non valide")
    if buttons.button("Continua senza modifiche"):
        answer({"edits": {}}, "Risposta non valida")  # ignora eventuali modifiche in tabella


def show_plan(plan: dict) -> None:
    st.subheader("Piano della giornata")
    if plan["conflicts"]:
        conflicts = ", ".join(plan["conflicts"])
        st.error(f"Giornata impossibile: questi obbligatori non stanno insieme: {conflicts}")
    elif plan["scheduled"]:
        st.dataframe(
            [
                {"Dalle": s["start"], "Alle": s["end"], "Task": s["title"]}
                for s in plan["scheduled"]
            ],
            hide_index=True,
        )
    else:
        st.info("Nessun task nel piano.")
    if plan["unscheduled"]:
        st.warning(f"Non inseriti: {', '.join(plan['unscheduled'])}")
    show_warnings(plan)


def show_review(plan: dict) -> None:
    show_plan(plan)
    buttons = st.container(horizontal=True, horizontal_alignment="right")
    if buttons.button("Continua senza modifiche", type="primary"):
        answer({"accept": True}, "Risposta non valida")
    if buttons.button("Modifica i task"):
        answer({"accept": False}, "Risposta non valida")


def show_final(result: dict) -> None:
    # TODO: quando ci sarà il database, il grafo salverà il piano in un nodo dopo la revisione
    st.success("Piano confermato.")
    show_plan(plan_summary(result["schedule"], result["tasks"], all_warnings(result)))

    tasks = approval(result["tasks"], result["rejected"], [])
    st.subheader("Task confermati")
    st.dataframe(tasks_table(tasks["tasks"]), column_config=COLUMNS, hide_index=True)
    show_rejected(tasks)


st.title("Agentic day planner")

# in un form Invio equivale al bottone; text_input perché in text_area Invio va a capo
with st.form("sentence"):
    text = st.text_input(
        "Cosa devi fare?",
        placeholder="domani devo studiare 2 ore, dentista alle 15, se riesco la spesa",
    )
    submitted = st.form_submit_button("Pianifica")
if submitted:
    if text.strip():
        with st.spinner("Sto leggendo la frase..."):
            start_planning(text)
    else:
        st.warning("Scrivi cosa devi fare.")

# fuori dagli if dei bottoni: ciò che è in session_state resta visibile a ogni esecuzione;
# la schermata dipende dalla domanda a cui il grafo aspetta risposta ("step")
if "final" in st.session_state:
    show_final(st.session_state.final)
elif "pending" in st.session_state:
    if st.session_state.pending["step"] == CONFIRM_TASKS:
        show_confirmation(st.session_state.pending)
    elif st.session_state.pending["step"] == REVIEW_PLAN:
        show_review(st.session_state.pending)
