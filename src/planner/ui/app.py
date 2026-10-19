"""Streamlit interface: a caller of the planner graph, like the tests.

Run with: python -m streamlit run src/planner/ui/app.py
"""

import os

# prima di importare langgraph: checkpoint in modalità strict, come nei test
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

import uuid
from datetime import date, timedelta

import pandas as pd
import psycopg
import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from planner.agents.approval import (
    CONFIRM_PREFERENCES,
    CONFIRM_TASKS,
    RESOLVE_CONFLICT,
    REVIEW_PLAN,
    SUGGEST_ACTIVITIES,
    approval,
    plan_summary,
)
from planner.agents.critic import duration_text
from planner.agents.graph import all_warnings, build_graph
from planner.config import Settings
from planner.dates import long_italian_date
from planner.db.repository import PostgresPlanRepository, PostgresPreferenceRepository
from planner.llm.factory import build_embedder, build_llm_client
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
def _connected_repository(url: str) -> PostgresPlanRepository:
    """The repository, once the database answered. Raises if it does not.

    cache_resource does not store a result when the function raises: a database that
    is down when the app starts is tried again on the next run, not forgotten forever.
    """
    with psycopg.connect(url, connect_timeout=3):
        pass
    return PostgresPlanRepository(url)


def get_repository() -> PostgresPlanRepository | None:
    """The plan repository, or None if the database is not reachable now (plans are not saved)."""
    try:
        return _connected_repository(Settings().database_url)
    except psycopg.OperationalError:
        return None


@st.cache_resource
def purge_on_startup(url: str) -> int:
    """Delete the days older than two weeks, once per database; return how many.

    Called only when the database answers, so a start with Docker off does not skip it.
    """
    return PostgresPlanRepository(url).purge_old_days()


def get_preferences() -> PostgresPreferenceRepository | None:
    """The preference memory: only with the database."""
    repository = get_repository()
    return PostgresPreferenceRepository(repository.conninfo) if repository else None


@st.cache_resource
def _build_graph(with_database: bool):
    """One graph with the database and one without, each created once per server.

    A new InMemorySaver would forget the paused graphs, so the graph is cached; the
    flag in the key makes the app use the graph with saving and memory as soon as the
    database answers, instead of keeping the one built while it was down.
    """
    return build_graph(
        build_llm_client(Settings()),
        checkpointer=InMemorySaver(),
        repository=get_repository() if with_database else None,
        embedder=build_embedder(Settings()),
        preferences=get_preferences() if with_database else None,
    )


def get_graph():
    """The graph for this run: with saving and memory if the database answers."""
    return _build_graph(get_repository() is not None)


def graph_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def remember(result: dict) -> None:
    """Store where the graph is: waiting for an answer (pending) or finished (final)."""
    if "__interrupt__" in result:
        (interrupt_,) = result["__interrupt__"]
        st.session_state.pending = interrupt_.value
        if interrupt_.value["step"] in (CONFIRM_TASKS, RESOLVE_CONFLICT):
            st.session_state.round += 1  # giro nuovo -> tabella nuova (vedi key del data_editor)
    else:
        st.session_state.pop("pending", None)
        st.session_state.final = result


def start_planning(text: str, day_date: date) -> None:
    """Run the graph until its first question."""
    st.session_state.thread_id = str(uuid.uuid4())  # una conversazione nuova per ogni frase
    st.session_state.round = 0
    st.session_state.pop("final", None)
    start = {"user_input": text, "day": DayConfig(), "day_date": day_date}
    remember(get_graph().invoke(start, graph_config()))


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


def edit_table(tasks: list[dict]) -> pd.DataFrame:
    """Editable task table; returns the table with the user's changes."""
    return st.data_editor(
        tasks_table(tasks),
        column_config=COLUMNS,
        disabled=READ_ONLY,
        hide_index=True,
        # una tabella nuova per ogni frase e per ogni giro di correzioni
        key=f"editor-{st.session_state.thread_id}-{st.session_state.round}",
    )


def right_aligned_buttons():
    # bottoni affiancati e allineati a destra (st.columns li allargherebbe a metà pagina)
    return st.container(horizontal=True, horizontal_alignment="right")


def show_saved_day(saved: dict) -> None:
    """The plan already saved for the date: merged by default, or replaced if the user chose so."""
    day = italian_date(saved["day_date"])
    if saved["replaced"]:
        st.warning(f"Il piano già salvato per il {day} verrà sostituito da questo.")
        return
    st.info(
        f"Hai già un piano per il {day}: i nuovi task verranno aggiunti negli spazi liberi, "
        "quelli già in agenda restano dove sono."
    )
    st.markdown("**Già in agenda**")
    st.caption(f"«{saved['user_input']}»")
    show_schedule(saved)


def show_confirmation(summary: dict) -> None:
    st.subheader("Controlla i task")
    saved = summary.get("saved_day")
    if saved:
        show_saved_day(saved)
        st.markdown("**Nuovi task**")
    if summary["tasks"]:
        st.caption(
            "Puoi cambiare durata, priorità, obbligo e orari prima di pianificare. "
            "Svuota un orario per togliere il vincolo."
        )
        edited = edit_table(summary["tasks"])
    else:
        st.info("Nessun task riconosciuto nella frase.")
        edited = pd.DataFrame()
    show_rejected(summary)
    show_warnings(summary)

    # un solo bottone: diff_edits capisce da solo se qualcosa è cambiato ({"edits": {}} se no)
    buttons = right_aligned_buttons()
    if buttons.button("Conferma e pianifica", type="primary"):
        answer(diff_edits(summary["tasks"], edited.to_dict("index")), "Correzioni non valide")
    if saved and not saved["replaced"] and buttons.button("Sostituisci il piano salvato"):
        response = diff_edits(summary["tasks"], edited.to_dict("index"))
        answer(response | {"replace_saved": True}, "Correzioni non valide")


def show_conflict(summary: dict) -> None:
    st.subheader("Giornata impossibile")
    st.error(
        "Questi task obbligatori non possono stare tutti nella giornata. "
        "Togli l'obbligo a uno di loro, oppure cambia un orario o una durata."
    )
    edited = edit_table(summary["tasks"])
    show_warnings(summary)

    # niente "continua senza modifiche": un piano impossibile non si può accettare
    if right_aligned_buttons().button("Riprova a pianificare", type="primary"):
        answer(diff_edits(summary["tasks"], edited.to_dict("index")), "Correzioni non valide")


def show_schedule(plan: dict) -> None:
    """The scheduled tasks as a table, plus the ones left out."""
    if plan["scheduled"]:
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


def show_plan(plan: dict) -> None:
    st.subheader("Piano della giornata")
    show_schedule(plan)
    show_warnings(plan)


def italian_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def show_review(plan: dict) -> None:
    # si arriva qui solo se qualche task non entra: è il motivo della domanda
    show_plan(plan)
    missing = plan["unscheduled"]
    verb = "non entra" if len(missing) == 1 else "non entrano"
    st.write(f"**{', '.join(missing)}** {verb} nella giornata. Ti va bene così?")
    buttons = right_aligned_buttons()
    if buttons.button("Continua senza modifiche", type="primary"):
        answer({"accept": True}, "Risposta non valida")
    if buttons.button("Modifica i task"):
        answer({"accept": False}, "Risposta non valida")


def show_critique(critique: dict) -> None:
    """Facts first, as data computed in Python; then the critic's comment, as an opinion.

    The 7B sometimes gets a detail wrong in its comment: shown this way, a mistake
    never contradicts a number the user can see.
    """
    facts = st.container(horizontal=True)
    facts.metric(
        "Tempo occupato",
        f"{duration_text(critique['busy_minutes'])} su {duration_text(critique['total_minutes'])}",
        help=f"{critique['busy_percent']}% della giornata",
        border=True,
    )
    longest = critique["longest_slot"]
    facts.metric(
        "Libero più lungo",
        f"{longest['start']}–{longest['end']}" if longest else "nessuno",
        border=True,
    )
    st.caption("Commento del Critico")
    st.info(critique["assessment"])
    # le preferenze date al Critico (le più vicine ai task): vero per costruzione.
    # Quali abbia applicato davvero il modello non è affidabile, quindi non si mostra
    considered = critique.get("recalled_preferences", [])
    if considered:
        st.caption("🧠 Preferenze considerate: " + "; ".join(considered))
    elif get_preferences() is not None:
        # la memoria c'è ma è vuota: lo si dice, invece di non mostrare niente
        st.caption("🧠 Nessuna preferenza ricordata finora da considerare.")


def show_suggestions(critique: dict) -> None:
    show_plan(critique["plan"])  # il piano su cui il Critico si esprime
    st.subheader("Il Critico")
    show_critique(critique)
    st.write("Attività che potresti aggiungere:")
    st.dataframe(
        [
            {
                "Attività": s["title"],
                "Categoria": s["category"],
                "Durata (min)": s["duration_min"],
                "Perché": s["reason"],
            }
            for s in critique["suggestions"]
        ],
        hide_index=True,
    )
    show_warnings(critique)
    # TODO passo 3: scegliere quali proposte aggiungere al piano
    if right_aligned_buttons().button("Va bene così", type="primary"):
        answer({"accepted": []}, "Risposta non valida")


def show_preferences_confirmation(question: dict) -> None:
    """New preferences found in the sentence: the user picks which to remember.

    Next to a preference close to one already saved, the saved one can be deleted:
    that is how the user resolves a contradiction ("la sera" instead of "la mattina").
    """
    st.subheader("Ho capito queste preferenze")
    st.caption("Spunta quelle da ricordare: le userò per le prossime giornate.")
    thread = st.session_state.thread_id
    keep, delete = [], []
    for pref in question["preferences"]:
        with st.container(border=True):
            if st.checkbox(pref["text"], value=True, key=f"pref-{thread}-{pref['index']}"):
                keep.append(pref["index"])
            st.caption(f"«{pref['source']}»")
            for saved in pref["similar"]:
                label = f"Cancella quella già salvata: {saved['text']}"
                if st.checkbox(label, value=False, key=f"pref-del-{thread}-{saved['id']}"):
                    delete.append(saved["id"])
    if right_aligned_buttons().button("Conferma", type="primary"):
        answer({"keep": keep, "delete": delete}, "Risposta non valida")


def show_save_result(saved: dict | None) -> None:
    """The outcome of saving, at the bottom: it is the last thing that happened."""
    st.divider()
    if saved is None:
        st.success("Piano confermato.", icon="✅")  # database non raggiungibile: non salvato
    elif saved["saved"]:
        st.success(saved["message"], icon="✅")
    else:
        # un piano non salvato va notato: avviso, non una semplice informazione
        st.warning(saved["message"], icon="⚠️")


def show_final(result: dict) -> None:
    show_plan(plan_summary(result["schedule"], result["tasks"], all_warnings(result)))
    if "critique" in result:
        st.subheader("Il Critico")
        show_critique(result["critique"])

    tasks = approval(result["tasks"], result["rejected"], [])
    st.subheader("Task confermati")
    # confermati non vuol dire inseriti: la colonna dice dove è finito ognuno,
    # così un task escluso dal piano non sembra rientrato
    slots = {
        item.task_id: f"{fmt_time(item.start_min)}–{fmt_time(item.end_min)}"
        for item in result["schedule"].scheduled
    }
    table = tasks_table(tasks["tasks"])
    table.insert(0, "slot", [slots.get(task_id, "non inserito") for task_id in table.index])
    st.dataframe(
        table,
        column_config={"slot": st.column_config.TextColumn("Nel piano")} | COLUMNS,
        hide_index=True,
    )
    show_rejected(tasks)

    show_save_result(result.get("save_result"))
    # il passaggio delle preferenze si vede sempre, anche quando non c'era niente da chiedere
    if "preference_candidates" in result:
        remembered = result.get("preference_result")
        if remembered and remembered["message"]:
            st.info(remembered["message"], icon="🧠")
        elif not result["preference_candidates"]:
            st.caption("🧠 Nessuna preferenza da ricordare in questa frase.")
        else:
            st.caption("🧠 Nessuna preferenza ricordata.")


# nomi italiani scritti a mano: strftime("%A") dipende dalla lingua del sistema
@st.dialog("Preferenze ricordate", width="large")
def show_preferences() -> None:
    """The remembered preferences, each with a button to delete it.

    A click inside a dialog reruns only the dialog function (a fragment): the delete
    button uses a callback, so the deletion happens before the list is drawn again.
    """
    try:
        preferences = get_preferences().all()
    except psycopg.OperationalError:
        st.error("Database non raggiungibile.")
        return
    if not preferences:
        st.info("Nessuna preferenza ricordata: nascono dalle frasi delle giornate salvate.")
        return
    st.caption("Le userò per le prossime giornate. Elimina quelle che non valgono più.")
    for pref in preferences:
        with st.container(border=True):
            text_column, button_column = st.columns([5, 1], vertical_alignment="center")
            text_column.markdown(f"**{pref.text}**")
            times = "1 volta" if pref.times_seen == 1 else f"{pref.times_seen} volte"
            text_column.caption(
                f"Vista {times} · ultima il {pref.last_seen:%d/%m/%Y} · «{pref.source}»"
            )
            # on_click: Streamlit chiama delete PRIMA della riesecuzione, qualunque parte venga
            # rieseguita (solo la finestra nel browser, tutta l'app nei test): l'elenco che
            # segue è già senza la preferenza cancellata
            button_column.button(
                "Elimina",
                key=f"delete-pref-{pref.id}",
                on_click=get_preferences().delete,
                args=(pref.id,),
            )


@st.dialog("Storico", width="large")
def show_history() -> None:
    """Saved days in a pop-up: for each day a header and its plan as a table.

    A function decorated with st.dialog opens as a modal when called; it closes
    with the X, with Esc or by clicking outside. The totals come from the
    day_summary view, the plans from one query for all days.
    """
    repository = get_repository()
    try:
        days = repository.history()
        plans = repository.history_plans()
    except psycopg.OperationalError:
        st.error("Database non raggiungibile.")
        return
    if not days:
        st.info("Nessuna giornata salvata.")
        return
    for d in days:
        day = d.day_date
        free = d.day_minutes - d.busy_minutes
        st.markdown(f"**{long_italian_date(day)}** · tempo libero {duration_text(free)}")
        st.caption(f"«{d.user_input}»")
        plan = plans.get(day, [])
        if plan:
            st.dataframe(
                [
                    {"Dalle": fmt_time(s.start_min), "Alle": fmt_time(s.end_min), "Task": s.title}
                    for s in plan
                ],
                hide_index=True,
            )
        else:
            st.info("Nessun task nel piano.")


# intestazione: titolo a sinistra, Storico sulla stessa riga a destra,
# dove stanno le azioni che valgono per tutta l'app
title_column, action_column = st.columns([4, 1], vertical_alignment="center")
title_column.title("Agentic day planner")
if get_repository() is None:
    st.warning("Database non raggiungibile: i piani non verranno salvati. Avvia Docker.")
else:
    purged = purge_on_startup(get_repository().conninfo)
    if purged and not st.session_state.get("purge_shown"):
        # una notifica sola per sessione: toast scompare da solo dopo qualche secondo
        days = "1 giornata" if purged == 1 else f"{purged} giornate"
        st.toast(f"Cancellate {days} più vecchie di 2 settimane.", icon="🧹")
        st.session_state.purge_shown = True
    actions = action_column.container(horizontal=True, horizontal_alignment="right")
    # aprono le finestre; senza database i bottoni non ci sono
    if actions.button("📅 Storico"):
        show_history()
    if actions.button("🧠 Preferenze"):
        show_preferences()

# in un form Invio equivale al bottone; text_input perché in text_area Invio va a capo
with st.form("sentence"):
    day_date = st.date_input("Giorno", value=date.today() + timedelta(days=1), format="DD/MM/YYYY")
    text = st.text_input(
        "Cosa devi fare?",
        placeholder="devo studiare 2 ore, dentista alle 15, se riesco la spesa",
    )
    submitted = st.form_submit_button("Pianifica")
if submitted:
    if text.strip():
        with st.spinner("Sto leggendo la frase..."):
            start_planning(text, day_date)
    else:
        st.warning("Scrivi cosa devi fare.")

# fuori dagli if dei bottoni: ciò che è in session_state resta visibile a ogni esecuzione;
# la schermata dipende dalla domanda a cui il grafo aspetta risposta ("step")
if "final" in st.session_state:
    show_final(st.session_state.final)
elif "pending" in st.session_state:
    step = st.session_state.pending["step"]
    if step == CONFIRM_TASKS:
        show_confirmation(st.session_state.pending)
    elif step == RESOLVE_CONFLICT:
        show_conflict(st.session_state.pending)
    elif step == REVIEW_PLAN:
        show_review(st.session_state.pending)
    elif step == SUGGEST_ACTIVITIES:
        show_suggestions(st.session_state.pending)
    elif step == CONFIRM_PREFERENCES:
        show_preferences_confirmation(st.session_state.pending)
