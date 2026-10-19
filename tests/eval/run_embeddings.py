"""Measure how nomic-embed-text sees our preferences, to choose SIMILAR_MIN.

New preferences and tasks search as "query", saved preferences are "document".
Being close does not mean saying the same thing ("studiare la mattina" / "la sera"):
the threshold only has to keep every pair to show (same or contradicting) above the
unrelated ones; the judge and the user decide the rest.

Needs Ollama running. Run with: python tests/eval/run_embeddings.py
"""

from planner.agents.preferences import SIMILAR_MIN
from planner.config import Settings
from planner.llm.embedder import cosine_similarity
from planner.llm.factory import build_embedder

# (preferenza nuova, salvata, tipo): "uguale" e "contraddizione" vanno mostrate
PAIRS = [
    ("la mattina si concentra meglio sullo studio", "preferisce studiare la mattina", "uguale"),
    ("fa la palestra di sera, dopo il lavoro", "preferisce la palestra la sera", "uguale"),
    ("non le piace lavorare dopo cena", "dopo cena non vuole lavorare", "uguale"),
    ("preferisce correre a mezzogiorno, prima di mangiare", "corre prima di pranzo", "uguale"),
    ("preferisce studiare la sera", "preferisce studiare la mattina", "contraddizione"),
    ("preferisce studiare la sera tardi", "odia studiare la sera tardi", "contraddizione"),
    ("fa la spesa il sabato pomeriggio", "fa la spesa il sabato mattina", "contraddizione"),
    ("preferisce andare in palestra la sera", "preferisce studiare la mattina", "diversa"),
    ("dopo cena non vuole lavorare", "fa la spesa il sabato", "diversa"),
    ("legge prima di dormire", "preferisce la palestra la sera", "diversa"),
]
PREFERENCES = [
    "preferisce andare in palestra la sera",
    "preferisce studiare la mattina",
    "fa la spesa il sabato",
    "dopo cena non vuole lavorare",
]
TASKS = ["palestra", "studio per l'esame", "spesa"]


def main() -> None:
    embedder = build_embedder(Settings())

    print(f"Candidate per i duplicati (soglia attuale {SIMILAR_MIN})")
    news = embedder.embed([new for new, _, _ in PAIRS], "query")
    saved = embedder.embed([old for _, old, _ in PAIRS], "document")
    shown, unrelated = [], []
    for (new, old, kind), n, s in zip(PAIRS, news, saved, strict=True):
        sim = cosine_similarity(n, s)
        (unrelated if kind == "diversa" else shown).append(sim)
        mark = "candidata" if sim >= SIMILAR_MIN else "-"
        print(f"  {sim:.3f} {mark:9} [{kind:14}] {new!r} / {old!r}")
    print(f"  da mostrare: da {min(shown):.3f}   diverse: fino a {max(unrelated):.3f}")
    ok = min(shown) >= SIMILAR_MIN > max(unrelated)
    print(f"  la soglia separa le due famiglie: {'sì' if ok else 'NO'}")

    print("\nRecupero: per ogni task, la preferenza più vicina")
    docs = embedder.embed(PREFERENCES, "document")
    for task, vector in zip(TASKS, embedder.embed(TASKS, "query"), strict=True):
        ranked = sorted(
            (
                (cosine_similarity(vector, d), text)
                for d, text in zip(docs, PREFERENCES, strict=True)
            ),
            reverse=True,
        )
        best, second = ranked[0], ranked[1]
        print(f"  {task!r:22} -> {best[0]:.3f} {best[1]!r}   (secondo {second[0]:.3f})")


if __name__ == "__main__":
    main()
