"""The REST API and its web page.

Before langgraph is imported (app.py imports it): checkpoints in strict msgpack mode, as in the
tests, so the API accepts in the graph state only the types declared in PlannerState.
"""

import os

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
