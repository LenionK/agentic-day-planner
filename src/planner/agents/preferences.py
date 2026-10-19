"""User preferences: extracted from the day's sentence by the LLM, judged for duplicates.

Two LLM jobs, both with the reasoning (or the source) written first:
- extract: which preferences does the sentence express? Usually none.
- judge: do two preferences say the same thing? Embeddings cannot tell "in the morning"
  from "in the evening" (measured in tests/eval/run_embeddings.py), the LLM can.
"""

from pydantic import BaseModel, Field

from planner.llm.base import LLMClient

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
- text: la preferenza in breve, in italiano, in terza persona. Usa lo STESSO momento del source, \
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
