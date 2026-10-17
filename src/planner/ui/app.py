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

from planner.agents.approval import approval
from planner.agents.graph import build_graph
from planner.config import Settings
from planner.llm.factory import build_llm_client
from planner.solver.models import DayConfig, fmt_time
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


def start_planning(text: str) -> None:
    """Run the graph until the confirmation and remember where it stopped."""
    st.session_state.thread_id = str(uuid.uuid4())  # una conversazione nuova per ogni frase
    st.session_state.pop("result", None)
    result = get_graph().invoke({"user_input": text, "day": DayConfig()}, graph_config())

    (pending,) = result["__interrupt__"]
    st.session_state.summary = pending.value


def resume_planning(response: dict) -> None:
    """Resume the paused graph with the user's edits; raises ValidationError if invalid."""
    st.session_state.result = get_graph().invoke(Command(resume=response), graph_config())


def tasks_table(tasks: list[dict]) -> pd.DataFrame:
    """Summary tasks as a table indexed by id, so each row keeps its task id."""
    # "HH:MM" -> time prima di creare la tabella: pandas trasformerebbe i None in NaN
    rows = [{**t, **{field: to_time(t[field]) for field in TIME_FIELDS}} for t in tasks]
    return pd.DataFrame(rows).set_index("id")[list(COLUMNS)]


def show_notes(summary: dict) -> None:
    for rejected in summary["rejected"]:
        st.error(f"Scartato: {rejected['title']} ({rejected['reason']})")
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
            key=f"editor-{st.session_state.thread_id}",  # frase nuova -> tabella nuova
        )
    else:
        st.info("Nessun task riconosciuto nella frase.")
        edited = pd.DataFrame()
    show_notes(summary)

    if st.button("Conferma e pianifica", type="primary"):
        response = diff_edits(summary["tasks"], edited.to_dict("index"))
        try:
            with st.spinner("Sto pianificando..."):
                resume_planning(response)
        except ValidationError as err:
            # il grafo resta in pausa: l'utente può correggere e riprovare
            st.error(f"Correzioni non valide: {short_errors(err)}")
        else:
            st.rerun()  # riparte lo script e mostra il piano


def show_plan(result: dict) -> None:
    schedule = result["schedule"]
    titles = {task.id: task.title for task in result["tasks"]}

    st.subheader("Piano della giornata")
    if schedule.status == "INFEASIBLE":
        conflicts = ", ".join(titles[task_id] for task_id in schedule.conflicts)
        st.error(f"Giornata impossibile: questi obbligatori non stanno insieme: {conflicts}")
    elif schedule.scheduled:
        st.dataframe(
            [
                {"Dalle": fmt_time(s.start_min), "Alle": fmt_time(s.end_min), "Task": s.title}
                for s in sorted(schedule.scheduled, key=lambda s: s.start_min)
            ],
            hide_index=True,
        )
    if schedule.unscheduled:
        missing = ", ".join(titles[task_id] for task_id in schedule.unscheduled)
        st.warning(f"Non inseriti: {missing}")

    # i task dopo le correzioni dell'editor, con gli avvisi del parser e dell'editor
    final = approval(result["tasks"], result["rejected"], result["warnings"])
    st.subheader("Task confermati")
    st.dataframe(tasks_table(final["tasks"]), column_config=COLUMNS, hide_index=True)
    show_notes(final)


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

# fuori dagli if dei bottoni: ciò che è in session_state resta visibile a ogni esecuzione
if "result" in st.session_state:
    show_plan(st.session_state.result)  # conversazione conclusa: niente più modifiche
elif "summary" in st.session_state:
    show_confirmation(st.session_state.summary)
