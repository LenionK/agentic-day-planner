from planner.agents.parser import parse_day
from planner.config import Settings
from planner.llm.factory import build_llm_client
from planner.solver.cpsat_scheduler import schedule
from planner.solver.models import DayConfig

settings = Settings()
client = build_llm_client(settings)
day = DayConfig(day_start_min=8 * 60, day_end_min=20 * 60)

text = "domani devo studiare 3 ore, dentista alle 15, palestra dopo le 17 e se riesco la spesa"
print(text)
parsed = parse_day(text, client)

print(f"Modello: {settings.llm_model}\n")
print("Task estratti:")
for t in parsed.tasks:
    print(
        f"  {t.id} {t.title}: {t.duration_min} min, priorità {t.priority}, "
        f"obbligatorio={t.required}, fisso={t.fixed_start_min}, "
        f"dopo={t.earliest_start_min}, entro={t.deadline_min}"
    )
for r in parsed.rejected:
    print(f"  SCARTATO {r.draft.title}: {r.reason}")

plan = schedule(parsed.tasks, day)

print(f"\nPiano ({plan.status}):")
for item in plan.scheduled:
    print(f"  {item.label}")
if plan.unscheduled:
    print(f"  Non inseriti: {plan.unscheduled}")
