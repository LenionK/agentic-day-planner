from datetime import date

from pydantic import BaseModel

from planner.db.preferences import SimilarPreference
from planner.db.repository import DayAlreadySaved
from planner.db.store import SavedDay
from planner.llm.base import LLMClient
from planner.llm.embedder import EMBED_DIM, Embedder, cosine_similarity
from planner.solver.models import DayConfig, Schedule, Task


class FakeClient(LLMClient):
    """Returns prepared answers, one per call, and records the messages it receives."""

    def __init__(self, responses: list[str], max_retries: int = 2) -> None:
        super().__init__(max_retries)
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        self.calls.append(list(messages))
        return self.responses.pop(0)


class FakePlanRepository:
    """In-memory PlanRepository: days by date, and a record of every save."""

    def __init__(self, *days: SavedDay) -> None:
        self.days: dict[date, SavedDay] = {d.day_date: d for d in days}
        self.saves: list[tuple[date, bool]] = []  # (data, replace) di ogni salvataggio
        self.conflict_on_save = False  # simula un salvataggio concorrente della stessa data

    def load(self, day_date: date) -> SavedDay | None:
        return self.days.get(day_date)

    def save(
        self,
        day_date: date,
        user_input: str,
        day: DayConfig,
        tasks: list[Task],
        plan: Schedule,
        sources: dict[str, str],
        *,
        replace: bool = False,
    ) -> int:
        self.saves.append((day_date, replace))
        if self.conflict_on_save or (day_date in self.days and not replace):
            raise DayAlreadySaved(day_date.isoformat())
        day_id = len(self.saves)
        self.days[day_date] = SavedDay(
            id=day_id,
            day_date=day_date,
            user_input=user_input,
            day=day,
            tasks=tasks,
            sources=sources,
            scheduled=sorted(plan.scheduled, key=lambda item: item.start_min),
        )
        return day_id


class FakeEmbedder(Embedder):
    """Returns the vectors chosen by the test and records the texts it receives (with prefix).

    Texts not in `vectors` get `default`; `dim` can be changed to return vectors of the
    wrong size, `extra` to return more vectors than texts.
    """

    def __init__(
        self, vectors: dict[str, list[float]] | None = None, default: list[float] | None = None
    ) -> None:
        self.vectors = vectors or {}
        self.default = default or unit(0)
        self.calls: list[list[str]] = []
        self.dim = EMBED_DIM
        self.extra = 0

    def _embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        result = []
        for text in texts:
            plain = text.split(": ", 1)[1]  # senza prefisso, per cercarlo in vectors
            result.append(self.vectors.get(plain, self.default)[: self.dim])
        return result + [self.default] * self.extra


def unit(i: int, dim: int = EMBED_DIM) -> list[float]:
    """A vector of length 1 along axis i: two different axes are unrelated (similarity 0)."""
    vector = [0.0] * dim
    vector[i] = 1.0
    return vector


class FakePreferenceRepository:
    """In-memory PreferenceRepository: similarity computed in Python like pgvector would."""

    def __init__(self) -> None:
        self.rows: dict[int, dict] = {}
        self.next_id = 1

    def add(self, text: str, source: str, embedding: list[float]) -> int:
        pref_id = self.next_id
        self.next_id += 1
        self.rows[pref_id] = {
            "text": text,
            "source": source,
            "embedding": embedding,
            "times_seen": 1,
        }
        return pref_id

    def similar(self, query: list[float], min_similarity: float) -> list[SimilarPreference]:
        found = [
            SimilarPreference(
                id=pref_id,
                text=row["text"],
                similarity=cosine_similarity(query, row["embedding"]),
            )
            for pref_id, row in self.rows.items()
        ]
        found = [p for p in found if p.similarity >= min_similarity]
        return sorted(found, key=lambda p: p.similarity, reverse=True)[:3]

    def mark_seen(self, pref_id: int) -> None:
        self.rows[pref_id]["times_seen"] += 1

    def delete(self, pref_id: int) -> bool:
        return self.rows.pop(pref_id, None) is not None

    def texts(self) -> list[str]:
        return [row["text"] for row in self.rows.values()]
