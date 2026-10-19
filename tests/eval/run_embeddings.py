"""Measure how nomic-embed-text sees our preferences, to choose the duplicate threshold.

Needs Ollama running. Run with: python tests/eval/run_embeddings.py
"""

from planner.config import Settings
from planner.llm.embedder import cosine_similarity
from planner.llm.factory import build_embedder

SAME = [
    ("preferisco studiare la mattina", "la mattina mi concentro meglio sullo studio"),
    ("preferisco andare in palestra la sera", "la palestra la faccio di sera, dopo il lavoro"),
    ("dopo cena non voglio lavorare", "non mi piace lavorare dopo cena"),
]
DIFFERENT = [
    ("preferisco studiare la mattina", "preferisco andare in palestra la sera"),
    # insidiosa: quasi le stesse parole, preferenze opposte. Non va unita
    ("preferisco studiare la mattina", "preferisco studiare la sera"),
    ("faccio la spesa il sabato", "dopo cena non voglio lavorare"),
]
PREFERENCES = [
    "preferisco andare in palestra la sera",
    "preferisco studiare la mattina",
    "faccio la spesa il sabato",
    "dopo cena non voglio lavorare",
]
QUERIES = ["palestra", "studio per l'esame", "spesa"]


def pair_similarities(embedder, pairs, kind):
    texts = [text for pair in pairs for text in pair]
    vectors = embedder.embed(texts, kind)
    return [cosine_similarity(vectors[i], vectors[i + 1]) for i in range(0, len(vectors), 2)]


def main() -> None:
    embedder = build_embedder(Settings())

    print("Duplicati, prefisso clustering")
    for label, pairs in (("stessa cosa", SAME), ("diverse", DIFFERENT)):
        for (a, b), sim in zip(
            pairs, pair_similarities(embedder, pairs, "clustering"), strict=True
        ):
            print(f"  [{label:11}] {sim:.3f}  {a!r} ~ {b!r}")

    print("\nRecupero: per ogni ricerca, le preferenze in ordine di similarità")
    docs = embedder.embed(PREFERENCES, "document")
    for mode in ("query", "document"):
        print(f"  ricerca con prefisso {mode}:")
        for query, q_vec in zip(QUERIES, embedder.embed(QUERIES, mode), strict=True):
            ranked = sorted(
                (
                    (cosine_similarity(q_vec, d), text)
                    for d, text in zip(docs, PREFERENCES, strict=True)
                ),
                reverse=True,
            )
            best, second = ranked[0], ranked[1]
            print(f"    {query!r:22} -> {best[0]:.3f} {best[1]!r}   (secondo {second[0]:.3f})")


if __name__ == "__main__":
    main()
