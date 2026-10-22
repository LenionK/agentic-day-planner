"""User preferences: extracted from the day's sentence by the LLM, judged for duplicates.

Two LLM jobs, both with the reasoning (or the source) written first:
- extract: which preferences does the sentence express? Usually none.
- judge: do two preferences say the same thing? Embeddings cannot tell "in the morning"
  from "in the evening" (measured in tests/eval/run_embeddings.py), the LLM can.
"""

from pydantic import BaseModel, ConfigDict, Field

from planner.db.repository import PreferenceRepository
from planner.llm.base import LLMClient
from planner.llm.embedder import Embedder
from planner.messages import Language, say

MAX_PREFERENCES = 5


class PreferenceDraft(BaseModel):
    """A preference as extracted by the LLM, fields in generation order.

    `source` first (grounding, as in the parser), then `cue`: the words that make it a
    preference and not a commitment. Only then `text`. A model that cannot point at a cue
    is usually looking at a commitment.
    """

    source: str = Field(min_length=1)
    cue: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ExtractedPreferences(BaseModel):
    preferences: list[PreferenceDraft] = Field(default_factory=list, max_length=MAX_PREFERENCES)


EXTRACT_PROMPT = """Leggi la frase con cui l'utente descrive la sua giornata e trova le sue \
PREFERENZE. Rispondi solo con il JSON richiesto.

Una preferenza è un'indicazione GENERALE su come l'utente vuole organizzarsi, valida anche \
per altri giorni: in che momento preferisce fare un'attività, cosa vuole evitare, un'abitudine.
La riconosci da parole come "preferisco", "sempre", "di solito", "odio", "non mi piace", \
"meglio", "evito", "non voglio", "mai".

NON sono preferenze gli impegni di quel giorno, anche con un orario o con un'altra persona: \
"dentista alle 15", "devo studiare 2 ore", "cena da Luca alle 20", "spesa e lavatrice" \
sono solo impegni.
Quasi sempre la frase NON contiene preferenze: in quel caso rispondi con una lista vuota.

Per ogni preferenza, in quest'ordine:
- source: copia parola per parola il pezzo di frase che la esprime. Non aggiungere parole.
- cue: copia dal source le parole che la rendono una preferenza e non un impegno \
(es. "sempre", "mi concentro meglio"). Se non ci sono, NON è una preferenza: non scriverla.
- text: la preferenza in breve, SEMPRE in italiano (mai in inglese), in terza persona. \
Inizia con un verbo: "preferisce", "evita", "non vuole", "fa", "nuota", "studia"... \
Non scrivere mai la parola "preference". Usa lo STESSO momento del source, \
senza cambiarlo: "prima di pranzo" resta "prima di pranzo", non diventa "pomeriggio".

Esempi:
Frase: "studio 2 ore la mattina perché mi concentro meglio, poi dentista alle 15"
Preferenze: source "la mattina perché mi concentro meglio", cue "mi concentro meglio", \
text "preferisce studiare la mattina"
Frase: "nuoto prima di pranzo, come sempre"
Preferenze: source "nuoto prima di pranzo, come sempre", cue "come sempre", \
text "nuota prima di pranzo"
Frase: "dentista alle 15, se riesco la spesa"
Preferenze: nessuna
Frase: "cena da Luca alle 20 e bucato"
Preferenze: nessuna"""


def _normalize(text: str) -> str:
    """Lowercase, no punctuation, single spaces: to check that a source is in the sentence."""
    for ch in ",.;:!?\"'«»":
        text = text.replace(ch, " ")
    return " ".join(text.lower().split())


def extract_preferences(
    sentence: str, client: LLMClient
) -> tuple[list[PreferenceDraft], list[str]]:
    """Preferences expressed in the sentence, and one warning per preference dropped.

    Dropped: a preference whose source is not in the sentence (made up), and one whose
    cue is not in its source (a commitment taken for a preference). The user confirms
    the others before they are saved: a wrong preference would affect every future day.
    """
    messages = [
        {"role": "system", "content": EXTRACT_PROMPT},
        {"role": "user", "content": sentence},
    ]
    parsed = client.generate(messages, ExtractedPreferences)

    kept, warnings = [], []
    sentence_norm = _normalize(sentence)
    for draft in parsed.preferences:
        source_norm = _normalize(draft.source)
        if source_norm not in sentence_norm:
            warnings.append(f"preferenza scartata (non compare nella frase): {draft.text}")
        elif _normalize(draft.cue) not in source_norm:
            # niente parola da preferenza nel pezzo citato: è un impegno
            warnings.append(f"preferenza scartata (nessun indizio nella frase): {draft.text}")
        else:
            kept.append(draft)
    return kept, warnings


class SameVerdict(BaseModel):
    """The judge's answer. The reasoning comes before the decision, as for the critic."""

    reasoning: str = Field(min_length=1)
    same: bool


JUDGE_PROMPT = """Ricevi due preferenze dello stesso utente. Decidi se dicono la stessa cosa. \
Rispondi solo con il JSON richiesto.

- reasoning: una frase che confronta attività, momento della giornata, giorni ed eventuali \
negazioni delle due preferenze.
- same: true solo se esprimono la stessa preferenza, anche con parole diverse. \
Se anche uno solo tra attività, momento, giorno o negazione è diverso, false.

Esempi:
"preferisce studiare la mattina" / "la mattina si concentra meglio sullo studio" -> same true
"preferisce studiare la mattina" / "preferisce studiare la sera" -> same false (momento diverso)"""


def same_preference(new: str, existing: str, client: LLMClient) -> bool:
    """Whether two preferences say the same thing (called only for close vectors)."""
    messages = [
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": f'Preferenza A: "{new}"\nPreferenza B: "{existing}"'},
    ]
    return client.generate(messages, SameVerdict).same


# sopra questa similarità (nuova come query, salvate come document) una preferenza salvata
# è una candidata: il giudice decide se è la stessa, l'utente se cancellarla.
# Misurata in run_embeddings.py: le coppie da mostrare (uguali o in contraddizione)
# partivano da 0.66, le preferenze diverse arrivavano a 0.62
SIMILAR_MIN = 0.63


class PreferencesResponse(BaseModel):
    """The user's answer: which new preferences to remember, which saved ones to delete."""

    model_config = ConfigDict(extra="forbid")

    keep: list[int]  # posizioni delle preferenze nuove da ricordare
    delete: list[int] = Field(default_factory=list)  # id delle salvate simili da cancellare


def find_candidates(
    sentence: str, client: LLMClient, embedder: Embedder, repository: PreferenceRepository
) -> tuple[list[dict], list[str]]:
    """Preferences of the sentence, each with what the memory already knows about it.

    For each one: the saved preferences close by vector are asked to the judge in order;
    the first one judged the same makes it a duplicate (`duplicate_of`), otherwise the
    close ones are kept as `similar`, for the user to decide. Plain JSON data for the state.
    """
    drafts, warnings = extract_preferences(sentence, client)
    vectors = embedder.embed([d.text for d in drafts], "query")

    candidates = []
    for draft, vector in zip(drafts, vectors, strict=True):
        duplicate_of, similar = None, []
        for saved in repository.similar(vector, SIMILAR_MIN):
            if same_preference(draft.text, saved.text, client):
                duplicate_of = saved.id
                break
            similar.append({"id": saved.id, "text": saved.text})
        candidates.append(
            {
                "text": draft.text,
                "source": draft.source,
                "duplicate_of": duplicate_of,
                "similar": [] if duplicate_of else similar,
            }
        )
    return candidates, warnings


def store_preferences(
    candidates: list[dict],
    response: PreferencesResponse,
    embedder: Embedder,
    repository: PreferenceRepository,
    language: Language = "it",
) -> dict:
    """Remember what the user confirmed: duplicates seen again, new ones saved, old ones deleted.

    Only the saved preferences shown next to a candidate can be deleted, and only the
    new candidates can be kept: anything else in the answer is ignored.
    """
    for candidate in candidates:
        if candidate["duplicate_of"] is not None:
            repository.mark_seen(candidate["duplicate_of"])
    seen_again = sum(c["duplicate_of"] is not None for c in candidates)

    new = {i for i, c in enumerate(candidates) if c["duplicate_of"] is None}
    to_save = [candidates[i] for i in sorted(set(response.keep) & new)]
    texts = [c["text"] for c in to_save]
    documents = embedder.embed(texts, "document")
    for candidate, doc in zip(to_save, documents, strict=True):
        repository.add(candidate["text"], candidate["source"], doc)

    shown = {s["id"] for c in candidates for s in c["similar"]}
    deleted = sum(repository.delete(pref_id) for pref_id in set(response.delete) & shown)

    counts = {"preferences_saved": len(to_save), "preferences_seen_again": seen_again}
    counts["preferences_deleted"] = deleted
    parts = [say(key, language, count=count) for key, count in counts.items() if count]
    message = say("preferences_result", language, parts=", ".join(parts)) if parts else ""
    return {"saved": len(to_save), "seen_again": seen_again, "deleted": deleted, "message": message}


# quante preferenze dare al Critico: le più simili alle frasi dei task, senza soglia.
# Una soglia non separa le pertinenti dalle altre (misurato con titoli e source, query e
# document): il vettore ordina, il Critico decide quali valgono davvero
RECALL_LIMIT = 3
ANY_SIMILARITY = -1.0  # il coseno sta tra -1 e 1: nessuna esclusa, decide l'ordine


def recall_preferences(
    sources: list[str],
    embedder: Embedder,
    repository: PreferenceRepository,
    limit: int = RECALL_LIMIT,
) -> list[str]:
    """The saved preferences closest to the day's tasks, the closest first.

    The tasks are searched by their source (the user's words, more context than a title),
    embedded as documents like the preferences: the best combination measured.
    Each preference counts with its best similarity to any task.
    """
    best: dict[int, tuple[float, str]] = {}
    for vector in embedder.embed(sources, "document"):
        for pref in repository.similar(vector, ANY_SIMILARITY):
            if pref.id not in best or pref.similarity > best[pref.id][0]:
                best[pref.id] = (pref.similarity, pref.text)
    ranked = sorted(best.values(), reverse=True)
    return [text for _, text in ranked[:limit]]
