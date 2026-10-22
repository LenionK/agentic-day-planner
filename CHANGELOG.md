# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-10-22

One interface instead of two: the web page served by the API, redesigned with design rules,
in English or Italian, with a settings panel. The model runs twice as fast on a 6 GB card.

### Added

- **English and Italian**: the language is chosen in the settings (English by default,
  remembered); every request sends `Accept-Language`, and the API writes its messages (warnings,
  saving, preferences, errors) in that language, also after a switch in the middle of a plan.
  All the sentences for the user are in `planner/messages.py` and `static/i18n.js`, with tests
  that every key exists in both languages. The model writes task titles and the critic's comment
  in the chosen language (a line at the end of the prompts; Italian prompts unchanged); sentences
  are still read in Italian, and preferences stay Italian.
- **⚙️ Settings** panel: language, theme (System / Light / Dark) and the remembered preferences.
- README: contents, screenshots of the web page (dark theme, English; the settings in Italian).

### Changed

- **Web page redesigned** following design rules: steps indicator (Tasks → Plan → Critic →
  Preferences → Done), wait and errors next to the clicked button, the form collapses into one
  line during a plan ("New plan" asks before discarding it), one primary action per
  screen (blue; red only for what deletes), the plan as a timeline with the free time, outcome
  and calendar download first on the final screen, works at phone width.
- **Faster LLM calls**: new settings `LLM_NUM_GPU` (GPU layers; `99` puts all of qwen2.5:7b on a
  6 GB card) and `LLM_KEEP_ALIVE` (models stay loaded, `30m` by default); `LLM_NUM_CTX` defaults
  to 4096. Measured on a GTX 1060 6GB: 11 → 22–24 tokens/s, parser 13.0 → 8.6 s per sentence,
  same evaluation results.
- The API turns on strict checkpoints (`LANGGRAPH_STRICT_MSGPACK`), as the tests do.
- README: a compact overview of the graph, the full graph in a collapsible section.

### Removed

- **Streamlit interface**: the web page served by the API replaces it. It is still in v0.3.0.

### Fixed

- The history and preferences buttons stayed visible without the database.
- After an update the buttons of the page could stop answering: the browser reused an old `app.js`
  with the new page. The page and its files are now served with `Cache-Control: no-cache`.

## [0.3.0] - 2026-10-20

The planner now remembers: plans are saved day by day, preferences are learned from the user's
sentences, and the same flow is available as a REST API with its own web page.

### Added

- **Day critic**: free time computed in Python (busy minutes, longest free slot), an LLM review
  of the day and, when it looks too empty, up to three suggested activities.
- **Conflicts and review**: required tasks that cannot all fit go back to the user with only the
  conflicting tasks; the plan review is asked only when some task is left out.
- **PostgreSQL storage** with Alembic migrations (plain SQL revisions): `days` and `tasks` with
  a cascading foreign key, only the scheduled tasks saved, `day_summary` view, history of saved
  days, `purge_old_days` procedure that deletes days older than two weeks at startup.
- **Saved days**: a new sentence for a date that already has a plan is merged into it (saved
  tasks stay where they are) or replaces it, as the user chooses.
- **Memory of preferences** with pgvector and `nomic-embed-text` embeddings: preferences
  extracted from the sentence (source → cue → text), duplicates judged by the LLM among the
  closest vectors, confirmed by the user before saving; the three closest are recalled for the
  critic, which also receives the weekday. Evaluation scripts on development and held-out sets.
- **REST API** with FastAPI: `POST /plans` and `POST /plans/{thread_id}/resume` drive the graph
  one question at a time (422 for invalid answers, 404 unknown plan, 409 finished plan);
  `GET /days`, `GET /preferences`, `DELETE /preferences/{id}`, `GET /health`.
- **Calendar export**: `GET /days/{date}/plan.ics`, one event per planned task, stable UIDs,
  times in the `TIMEZONE` of the settings.
- **Web page** served by the API: the screens of the Streamlit app, history and preferences
  windows, download link for the calendar, dark theme.
- Streamlit: date picker, "Già in agenda" in the confirmation, 📅 Storico and 🧠 Preferenze
  windows, messages about the memory of preferences.
- `docs/`: a booklet in Italian on the technologies used (Pydantic, Ollama, FastAPI so far).

### Fixed

- Times edited in the Streamlit table are read as ISO strings (`17:00:00.000`).
- The Streamlit app tries the database again instead of remembering that it was down.

## [0.2.0] - 2026-10-17

First tagged release: the planner works end to end, from a sentence to an accepted plan.

### Added

- **Scheduler** with OR-Tools CP-SAT: no overlaps, time windows, fixed starts, hierarchical
  priority weights, required tasks, impossible tasks left out without breaking the plan.
- **LLM layer**: `LLMClient` interface with validation and retry, Ollama and LangChain clients,
  factory from `.env` settings.
- **Parser**: free text to validated tasks, with a grounding `source` per task, times converted
  in Python, made-up times removed with a warning, invalid tasks rejected with a reason.
  Evaluation set of 12 cases and `run_eval.py`.
- **LangGraph flow** with the user in the loop:
  - task confirmation with `interrupt`: JSON summary and answer validated with `response_schema`
  - editor that validates and applies the user's edits (duration, priority, required, times)
  - plan review after the scheduler, with a conditional edge: accept ends the graph,
    edit goes back to the confirmation starting from the tasks already edited
- **Streamlit interface**: editable task table (checkbox, priority menu, duration, time picker),
  "continue without changes" on both screens, plan view and confirmed plan.
- Checkpoints in strict msgpack mode in tests.
- README with installation and usage.

[0.4.0]: https://github.com/LenionK/agentic-day-planner/releases/tag/v0.4.0
[0.3.0]: https://github.com/LenionK/agentic-day-planner/releases/tag/v0.3.0
[0.2.0]: https://github.com/LenionK/agentic-day-planner/releases/tag/v0.2.0
