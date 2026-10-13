from ortools.sat.python import cp_model

from planner.solver.models import DayConfig, Schedule, ScheduledTask, Task


def schedule(tasks: list[Task], day: DayConfig) -> Schedule:
    model = cp_model.CpModel()
    present, starts, intervals = {}, {}, []
    impossible_required = []

    # 1. per ogni task: calcola la finestra valida e crea le variabili
    for t in tasks:
        n, d = t.id, t.duration_min

        # inizio più presto: giornata o earliest_start_min
        lo = day.day_start_min
        if t.earliest_start_min is not None:
            lo = max(lo, t.earliest_start_min)

        # fine più tardi: giornata o deadline_min
        latest_end = day.day_end_min
        if t.deadline_min is not None:
            latest_end = min(latest_end, t.deadline_min)
        hi = latest_end - d

        # orario fisso: il dominio si riduce a un solo valore, se è nella finestra
        if t.fixed_start_min is not None:
            if lo <= t.fixed_start_min <= hi:
                lo = hi = t.fixed_start_min
            else:
                hi = lo - 1  # orario fuori dalla finestra: nessuna posizione valida

        # finestra vuota: il task non può stare nella giornata
        if lo > hi:
            if t.required:
                impossible_required.append(n)
            continue

        present[n] = model.NewBoolVar(f"present_{n}")
        starts[n] = model.NewIntVar(lo, hi, f"start_{n}")
        end = model.NewIntVar(lo + d, hi + d, f"end_{n}")
        interval = model.NewOptionalIntervalVar(starts[n], d, end, present[n], f"interval_{n}")
        intervals.append(interval)

    # un obbligatorio che non entra nella giornata rende impossibile il piano
    if impossible_required:
        return Schedule(
            status="INFEASIBLE",
            unscheduled=[t.id for t in tasks],
            conflicts=impossible_required,
        )

    # 2. i task presenti non possono sovrapporsi
    model.AddNoOverlap(intervals)

    # 3. gli obbligatori sono assumption e non vincoli: se il piano è impossibile,
    #    il solver sa dire quali di loro sono incompatibili
    required = [t.id for t in tasks if t.required]
    model.AddAssumptions([present[n] for n in required])

    # 4. obiettivo: massimizzare la somma delle priorità dei task inclusi
    base = len(tasks) + 1
    weight = {p: base ** (p - 1) for p in range(1, 6)}

    model.Maximize(sum(weight[t.priority] * present[t.id] for t in tasks if t.id in present))

    # 5. risolvi, con un limite di 5 secondi
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)

    # 6. costruisci e restituisci lo Schedule
    if status == cp_model.INFEASIBLE:
        return Schedule(
            status="INFEASIBLE",
            unscheduled=[t.id for t in tasks],
            conflicts=_minimal_conflict(model, solver, required, present),
        )

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule(
            status=solver.StatusName(status),
            unscheduled=[t.id for t in tasks],
        )

    scheduled = []
    unscheduled = []
    for t in tasks:
        if t.id in present and solver.Value(present[t.id]):
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


def _minimal_conflict(
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    required: list[str],
    present: dict[str, cp_model.IntVar],
) -> list[str]:
    """Return the required tasks that cannot all fit together, keeping input order.

    CP-SAT gives a set that is sufficient but not always minimal, so each task is
    removed in turn: if the day stays impossible without it, it was not part of the conflict.
    """
    core_indices = set(solver.SufficientAssumptionsForInfeasibility())
    core = [n for n in required if present[n].Index() in core_indices] or list(required)

    for n in list(core):
        trial = [m for m in core if m != n]
        model.ClearAssumptions()
        model.AddAssumptions([present[m] for m in trial])
        if solver.Solve(model) == cp_model.INFEASIBLE:
            core = trial

    return core
