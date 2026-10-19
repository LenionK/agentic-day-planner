import math

import pytest

from planner.config import Settings
from planner.llm.embedder import EMBED_DIM, cosine_similarity
from planner.llm.factory import build_embedder
from planner.llm.ollama_embedder import OllamaEmbedder
from tests.fakes import FakeEmbedder, unit


@pytest.mark.parametrize(
    ("kind", "prefix"),
    [
        ("document", "search_document: "),
        ("query", "search_query: "),
        ("clustering", "clustering: "),
    ],
)
def test_each_kind_adds_its_prefix(kind, prefix):
    embedder = FakeEmbedder()

    embedder.embed(["palestra la sera", "studio la mattina"], kind)

    assert embedder.calls == [[prefix + "palestra la sera", prefix + "studio la mattina"]]


def test_vectors_come_back_in_the_order_of_the_texts():
    embedder = FakeEmbedder({"a": unit(1), "b": unit(2)})

    assert embedder.embed(["b", "a"], "document") == [unit(2), unit(1)]


def test_empty_list_makes_no_call():
    embedder = FakeEmbedder()

    assert embedder.embed([], "clustering") == []
    assert embedder.calls == []


def test_vector_of_the_wrong_size_is_rejected():
    embedder = FakeEmbedder()
    embedder.dim = 3

    with pytest.raises(ValueError, match=f"{EMBED_DIM} numbers, got 3"):
        embedder.embed(["palestra"], "document")


def test_more_vectors_than_texts_are_rejected():
    embedder = FakeEmbedder()
    embedder.extra = 1

    with pytest.raises(ValueError, match="expected 1 vectors, got 2"):
        embedder.embed(["palestra"], "document")


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ([1.0, 0.0], [1.0, 0.0], 1.0),  # stessa direzione
        ([1.0, 0.0], [-1.0, 0.0], -1.0),  # opposti
        ([1.0, 0.0], [0.0, 1.0], 0.0),  # perpendicolari: nessuna relazione
        ([3.0, 0.0], [1.0, 0.0], 1.0),  # la lunghezza non conta, solo la direzione
        ([1.0, 1.0], [1.0, 0.0], 1 / math.sqrt(2)),  # 45 gradi
    ],
)
def test_cosine_similarity(a, b, expected):
    assert cosine_similarity(a, b) == pytest.approx(expected)


def test_cosine_similarity_of_a_zero_vector_is_an_error():
    with pytest.raises(ValueError):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])


def test_factory_builds_an_ollama_embedder_from_the_settings():
    settings = Settings(embed_model="altro-modello", ollama_host="http://ollama:9999")

    embedder = build_embedder(settings)

    assert isinstance(embedder, OllamaEmbedder)
    assert (embedder.model, embedder.host) == ("altro-modello", "http://ollama:9999")
