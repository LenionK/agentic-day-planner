from abc import ABC, abstractmethod
from typing import Literal

# nomic-embed-text restituisce vettori di 768 numeri: la colonna vector(768) deve coincidere
EMBED_DIM = 768

# nomic-embed-text vuole davanti al testo l'intento: cosa si salva (document) e con cosa
# si cerca (query). Le preferenze si salvano come document; una preferenza nuova o un
# task cercano come query, sia per i duplicati sia per il recupero
PREFIXES = {"document": "search_document: ", "query": "search_query: "}
Kind = Literal["document", "query"]


class Embedder(ABC):
    """Turns texts into vectors: similar meanings give close vectors.

    Same template method as LLMClient: embed() does the common part (prefix and checks),
    subclasses only implement _embed() for a specific service.
    """

    @abstractmethod
    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per text, in the same order. The texts already have the prefix."""

    def embed(self, texts: list[str], kind: Kind) -> list[list[float]]:
        """Vectors for texts to store ("document") or to search with ("query").

        Raises ValueError if the service returns the wrong number of vectors or a
        vector of the wrong size: better here than when PostgreSQL rejects it.
        """
        if not texts:
            return []  # niente da calcolare: nessuna chiamata al servizio

        prefix = PREFIXES[kind]
        vectors = self._embed([prefix + text for text in texts])

        if len(vectors) != len(texts):
            raise ValueError(f"expected {len(texts)} vectors, got {len(vectors)}")
        for vector in vectors:
            if len(vector) != EMBED_DIM:
                raise ValueError(f"expected vectors of {EMBED_DIM} numbers, got {len(vector)}")
        return vectors


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """1 = same direction (same meaning), 0 = unrelated, -1 = opposite.

    nomic-embed-text returns vectors of length 1, for which this is just the dot product;
    dividing by the norms keeps it right for any vector. pgvector's <=> returns the
    distance, that is 1 - similarity.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        raise ValueError("cosine similarity of a zero vector is undefined")
    return dot / (norm_a * norm_b)
