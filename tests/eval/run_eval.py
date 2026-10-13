import json
import time
from pathlib import Path

from planner.agents.parser import parse_day, to_minutes
from planner.config import Settings
from planner.llm.factory import build_llm_client

CASES_PATH = Path(__file__).parent / "cases.jsonl"

# campo nel caso atteso -> campo del Task
TIME_FIELDS = {
    "fixed_start": "fixed_start_min",
    "earliest_start": "earliest_start_min",
    "deadline": "deadline_min",
}


def load_cases(path: Path) -> list[dict]:
    cases_list = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases_list.append(json.loads(line))
    return cases_list


def find_by_title(items, match: str):
    """Return the first item whose title contains `match` (case-insensitive), or None."""
    needle = match.lower()
    for item in items:
        if needle in item.title.lower():
            return item
    return None


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse spaces: to compare a source with the sentence."""
    for ch in ",.;:!?":
        text = text.replace(ch, " ")
    return " ".join(text.lower().split())


def check_case(case: dict, result) -> list[tuple[str, bool]]:
    """Restituisce una lista di controlli (nome_campo, superato)."""
    checks = []

    for exp in case["expected"]:
        task = find_by_title(result.tasks, exp["match"])
        checks.append(("found", task is not None))
        if task is None:
            continue

        checks.append(("priority", task.priority == exp["priority"]))
        checks.append(("required", task.required == exp["required"]))

        if "duration_min" in exp:
            checks.append(("duration_min", task.duration_min == exp["duration_min"]))

        for exp_field, task_field in TIME_FIELDS.items():
            expected_time = exp.get(exp_field)
            expected_min = to_minutes(expected_time) if expected_time is not None else None
            checks.append((exp_field, getattr(task, task_field) == expected_min))

    drafts = [r.draft for r in result.rejected]
    for exp in case.get("rejected", []):
        checks.append(("rejected", find_by_title(drafts, exp["match"]) is not None))

    return checks


def print_result(result) -> None:
    """Stampa task estratti, scartati e avvisi, per capire perché un caso è fallito."""
    for t in result.tasks:
        print(
            f"    - {t.title}: priorità {t.priority}, obbligatorio={t.required}, "
            f"fisso={t.fixed_start_min}, dopo={t.earliest_start_min}, entro={t.deadline_min}"
        )
        print(f"      source: {result.sources.get(t.id)!r}")
    for r in result.rejected:
        d = r.draft
        print(
            f"    - SCARTATO {d.title}: fisso={d.fixed_start}, dopo={d.earliest_start}, "
            f"entro={d.deadline}, durata={d.duration_min}"
        )
        print(f"      source: {d.source!r}")
        lines = r.reason.splitlines()
        print(f"      motivo: {lines[1].strip() if len(lines) > 1 else r.reason}")
    for w in result.warnings:
        print(f"    ! AVVISO {w}")


def main() -> None:
    settings = Settings()
    client = build_llm_client(settings)
    cases = load_cases(CASES_PATH)

    passed_cases = 0
    field_stats: dict[str, list[int]] = {}  # campo -> [superati, totali]
    durations = []
    sources_ok = sources_total = 0
    warnings_total = 0

    for i, case in enumerate(cases, start=1):
        start = time.perf_counter()
        try:
            result = parse_day(case["text"], client)
        except Exception as err:
            durations.append(time.perf_counter() - start)
            print(f"\n[{i}] ERRORE: {case['text']}\n    {type(err).__name__}: {err}")
            continue
        durations.append(time.perf_counter() - start)

        warnings_total += len(result.warnings)

        # il source deve essere una copia di un pezzo della frase
        all_sources = list(result.sources.values()) + [r.draft.source for r in result.rejected]
        for source in all_sources:
            sources_total += 1
            sources_ok += normalize(source) in normalize(case["text"])

        checks = check_case(case, result)
        for field, ok in checks:
            stats = field_stats.setdefault(field, [0, 0])
            stats[0] += ok
            stats[1] += 1

        if all(ok for _, ok in checks):
            passed_cases += 1
        else:
            failed = [field for field, ok in checks if not ok]
            print(f"\n[{i}] FALLITO: {case['text']}")
            print(f"    controlli non superati: {failed}")
            print_result(result)

    print(f"\nModello: {settings.llm_model} (contesto {settings.llm_num_ctx})")
    print(f"Casi corretti: {passed_cases}/{len(cases)}")
    print("Accuratezza per campo:")
    for field, (ok, total) in field_stats.items():
        print(f"  {field:<15} {ok}/{total}")
    print(f"Source copiati fedelmente: {sources_ok}/{sources_total}")
    print(f"Orari tolti (avvisi): {warnings_total}")
    print(f"Tempo medio: {sum(durations) / len(durations):.1f} s")


if __name__ == "__main__":
    main()
