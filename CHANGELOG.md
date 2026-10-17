# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

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

[0.2.0]: https://github.com/LenionK/agentic-day-planner/releases/tag/v0.2.0
