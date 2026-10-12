from ortools.sat.python import cp_model
from planner.solver.models import DayConfig, Schedule, ScheduledTask, Task


def schedule(tasks: list[Task], day: DayConfig) -> Schedule:
    model = cp_model.CpModel()
    present, starts, intervals = {}, {}, []

    # 1. per ogni task: present (bool), start (int), end (int), intervallo opzionale
    #    start va da day.day_start_min a day.day_end_min - durata
    for t in tasks:
        n, d = t.id, t.duration_min
        present[n] = model.NewBoolVar(f"present_{n}")
        starts[n] = model.NewIntVar(day.day_start_min, day.day_end_min -d, f"start_{n}")
        end = model.NewIntVar(day.day_start_min + d , day.day_end_min, f"end_{n}")
        interval = model.NewOptionalIntervalVar(starts[n], d, end, present[n], f"interval_{n}")
        intervals.append(interval)

    # 2. NoOverlap su tutti gli intervalli
    model.AddNoOverlap(intervals)

    # 3. obiettivo: massimizzare la somma di priority * present
    model.Maximize(sum(t.priority * present[t.id] for t in tasks))

    # 4. risolvi, con un limite di 5 secondi


    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)

    # 5. costruisci e restituisci lo Schedule
    
    print("Stato:", solver.StatusName(status))
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule(
            status=solver.StatusName(status),
            unscheduled=[t.id for t in tasks],
        )

    scheduled = []
    unscheduled = []
    for t in tasks:
        if solver.Value(present[t.id]):
            s = solver.Value(starts[t.id])
            scheduled.append(
                ScheduledTask(task_id=t.id, title=t.title, start_min=s, end_min=s + t.duration_min)
            )
        else:
            unscheduled.append(t.id)

    return Schedule(
        status=solver.StatusName(status),
        scheduled=sorted(scheduled, key=lambda item: item.start_min),
        unscheduled=unscheduled,
        objective=solver.ObjectiveValue(),
    )

  

   