from typing import NotRequired, TypedDict

from planner.agents.parser import RejectedTask
from planner.solver.models import DayConfig, Schedule, Task


class PlannerState(TypedDict):
    """State shared by the planner graph nodes.

    The caller provides `user_input` and `day`; every other field is written by a node.
    """

    # input
    user_input: str
    day: DayConfig

    # scritti dal Parser
    tasks: NotRequired[list[Task]]
    rejected: NotRequired[list[RejectedTask]]
    warnings: NotRequired[list[str]]
    sources: NotRequired[dict[str, str]]

    # scritto dallo scheduler
    schedule: NotRequired[Schedule]
