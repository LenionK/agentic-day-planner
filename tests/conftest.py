import os

# Checkpoint in modalità strict: LangGraph deserializza solo i tipi dichiarati nello
# stato del grafo (Task, DayConfig...), e la modalità permissiva verrà rimossa.
# Va impostata prima che langgraph venga importato: conftest viene caricato per primo.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
