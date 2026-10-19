"""Measure preference extraction and the duplicate judge with the real LLM.

Needs Ollama running. Run with:
    python tests/eval/run_preferences.py            # development set
    python tests/eval/run_preferences.py --holdout  # held-out set, only at the end

Development cases are the ones looked at while changing the prompt; held-out cases are
never used for that, so they measure the real result. None of them is a prompt example.
"""

import sys
import time

from planner.agents.preferences import extract_preferences, same_preference
from planner.config import Settings
from planner.llm.factory import build_llm_client

# (frase, ci sono preferenze?)
DEV_SENTENCES = [
    (
        "lezione alle 9, poi corsa: la faccio sempre prima di pranzo così il pomeriggio sono libero",
        True,
    ),
    ("non fissarmi riunioni il venerdì pomeriggio, e devo finire la relazione", True),
    ("cena dai miei alle 20 e lavatrice", False),
    ("ripassare inglese mezz'ora, odio studiare la sera tardi", True),
    ("spesa, palestra e chiamare il medico entro le 11", False),
    ("palestra dopo le 18, prima sono troppo stanco per allenarmi", True),
    ("devo studiare 3 ore e chiamare la banca entro le 12", False),
    # dalla prova vera nell'interfaccia: testi usciti in inglese
    ("studio 2 ore, la mattina mi concentro meglio", True),
    ("ripasso un'ora, ormai preferisco studiare la sera", True),
]
HOLDOUT_SENTENCES = [
    ("corso di yoga alle 18, la sera mi rilassa più che la mattina", True),
    ("pranzo con i colleghi alle 13 e poi call con il cliente", False),
    ("scrivo la tesi, ma mai dopo le 22 perché poi non dormo", True),
    ("lavare la macchina, pagare la bolletta e passare in posta", False),
    ("riunione di team alle 11; il lunedì di solito non prendo appuntamenti", True),
    ("aperitivo con Sara alle 19 e film", False),
    ("leggo un'ora: preferisco farlo prima di dormire", True),
    ("esame alle 9, ripasso la sera prima", False),
]

# (A, B, stessa preferenza?)
PAIRS = [
    ("corre prima di pranzo", "preferisce correre a mezzogiorno, prima di mangiare", True),
    (
        "non vuole riunioni il venerdì pomeriggio",
        "evita gli impegni di lavoro il venerdì dopo pranzo",
        True,
    ),
    ("non vuole riunioni il venerdì pomeriggio", "non vuole riunioni il lunedì mattina", False),
    ("odia studiare la sera tardi", "preferisce studiare la sera tardi", False),
    ("fa la spesa il sabato mattina", "fa la spesa il sabato pomeriggio", False),
    ("preferisce la palestra la sera", "preferisce correre la sera", False),
]


def main() -> None:
    holdout = "--holdout" in sys.argv
    sentences = HOLDOUT_SENTENCES if holdout else DEV_SENTENCES
    client = build_llm_client(Settings())

    print(f"Estrazione ({'verifica' if holdout else 'sviluppo'})")
    right = 0
    for sentence, has_prefs in sentences:
        start = time.perf_counter()
        prefs, warnings = extract_preferences(sentence, client)
        ok = bool(prefs) == has_prefs
        right += ok
        found = [f"{p.text} [cue: {p.cue}]" for p in prefs] or "nessuna"
        print(f"  {'OK ' if ok else 'NO '} {time.perf_counter() - start:4.1f}s  {sentence!r}")
        print(f"        -> {found}")
        for warning in warnings:
            print(f"           {warning}")
    print(f"  {right}/{len(sentences)} corrette")

    if holdout:
        return
    print("\nGiudice dei duplicati")
    right = 0
    for a, b, expected in PAIRS:
        same = same_preference(a, b, client)
        right += same == expected
        print(f"  {'OK ' if same == expected else 'NO '} same={same!s:5}  {a!r} / {b!r}")
    print(f"  {right}/{len(PAIRS)} corrette")


if __name__ == "__main__":
    main()
