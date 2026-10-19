import json

import pytest
from pydantic import ValidationError

from planner.agents.preferences import (
    ExtractedPreferences,
    PreferenceDraft,
    PreferencesResponse,
    SameVerdict,
    extract_preferences,
    find_candidates,
    same_preference,
    store_preferences,
)
from planner.llm.embedder import EMBED_DIM
from tests.fakes import FakeClient, FakeEmbedder, FakePreferenceRepository, unit


def extracted(*prefs: tuple[str, str, str]) -> str:
    """The LLM answer: one (source, cue, text) per preference."""
    return json.dumps({"preferences": [{"source": s, "cue": c, "text": t} for s, c, t in prefs]})


def test_preference_grounded_in_the_sentence_is_kept():
    sentence = "Studio 2 ore la mattina, perché mi concentro meglio; poi dentista alle 15"
    client = FakeClient(
        [
            extracted(
                (
                    "la mattina perché mi concentro meglio",
                    "Mi concentro meglio",
                    "preferisce studiare la mattina",
                )
            )
        ]
    )

    prefs, warnings = extract_preferences(sentence, client)

    # punteggiatura e maiuscole diverse non contano
    assert [p.text for p in prefs] == ["preferisce studiare la mattina"]
    assert warnings == []
    assert client.calls[0][1]["content"] == sentence


def test_made_up_preference_is_dropped_with_a_warning():
    client = FakeClient(
        [extracted(("preferisco il pomeriggio", "preferisco", "preferisce il pomeriggio"))]
    )

    prefs, warnings = extract_preferences("dentista alle 15", client)

    assert prefs == []
    assert warnings == ["preferenza scartata (non compare nella frase): preferisce il pomeriggio"]


def test_commitment_without_a_cue_in_its_source_is_dropped():
    # il modello cita un pezzo vero ma indica un indizio che lì non c'è: è un impegno
    client = FakeClient([extracted(("cena dai miei alle 20", "sempre", "cena con la famiglia"))])

    prefs, warnings = extract_preferences("cena dai miei alle 20 e lavatrice", client)

    assert prefs == []
    assert warnings == ["preferenza scartata (nessun indizio nella frase): cena con la famiglia"]


def test_extraction_schema_writes_source_and_cue_before_the_text():
    assert list(PreferenceDraft.model_fields) == ["source", "cue", "text"]


def test_sentence_with_only_commitments_gives_no_preferences():
    client = FakeClient([extracted()])

    assert extract_preferences("dentista alle 15, se riesco la spesa", client) == ([], [])


def test_five_preferences_are_accepted():
    ExtractedPreferences.model_validate(
        {"preferences": [{"source": "x", "cue": "x", "text": "y"}] * 5}
    )


def test_too_many_preferences_are_rejected_by_the_schema():
    with pytest.raises(ValidationError):
        ExtractedPreferences.model_validate(
            {"preferences": [{"source": "x", "cue": "x", "text": "y"}] * 6}
        )


def test_judge_schema_puts_the_reasoning_before_the_decision():
    assert list(SameVerdict.model_fields) == ["reasoning", "same"]


@pytest.mark.parametrize("same", [True, False])
def test_judge_returns_the_llm_decision_and_sends_both_preferences(same):
    answer = json.dumps({"reasoning": "confronto", "same": same})
    client = FakeClient([answer])

    result = same_preference("studiare la sera", "studiare la mattina", client)

    assert result is same
    user_message = client.calls[0][1]["content"]
    assert "studiare la sera" in user_message and "studiare la mattina" in user_message


# --- memoria: candidate e salvataggio ------------------------------------------------


def near(i: int, j: int, cos: float) -> list[float]:
    """A unit vector with cosine similarity `cos` to unit(i)."""
    vector = [0.0] * EMBED_DIM
    vector[i], vector[j] = cos, (1 - cos * cos) ** 0.5
    return vector


def judge(same: bool) -> str:
    return json.dumps({"reasoning": "confronto", "same": same})


MORNING = "preferisce studiare la mattina"
EVENING = "preferisce studiare la sera"
SENTENCE = "studio la sera, preferisco così"


def memory_with_morning() -> tuple[FakePreferenceRepository, int]:
    repository = FakePreferenceRepository()
    pref_id = repository.add(MORNING, "la mattina", unit(1))
    return repository, pref_id


def test_close_but_different_preference_is_shown_with_the_saved_one():
    repository, morning_id = memory_with_morning()
    embedder = FakeEmbedder({EVENING: near(1, 2, 0.93)})  # vicinissime per i vettori
    client = FakeClient([extracted((SENTENCE, "preferisco", EVENING)), judge(False)])

    candidates, _ = find_candidates(SENTENCE, client, embedder, repository)

    assert candidates == [
        {
            "text": EVENING,
            "source": SENTENCE,
            "duplicate_of": None,
            "similar": [{"id": morning_id, "text": MORNING}],
        }
    ]
    assert len(client.calls) == 2  # estrazione + un giudizio


def test_preference_judged_the_same_is_a_duplicate():
    repository, morning_id = memory_with_morning()
    paraphrase = "la mattina studia meglio"
    embedder = FakeEmbedder({paraphrase: near(1, 2, 0.90)})
    client = FakeClient([extracted((SENTENCE, "preferisco", paraphrase)), judge(True)])

    (candidate,), _ = find_candidates(SENTENCE, client, embedder, repository)

    assert (candidate["duplicate_of"], candidate["similar"]) == (morning_id, [])


def test_far_preference_is_new_and_the_judge_is_not_called():
    repository, _ = memory_with_morning()
    embedder = FakeEmbedder({EVENING: unit(7)})  # lontana da tutto
    client = FakeClient([extracted((SENTENCE, "preferisco", EVENING))])

    (candidate,), _ = find_candidates(SENTENCE, client, embedder, repository)

    assert (candidate["duplicate_of"], candidate["similar"]) == (None, [])
    assert len(client.calls) == 1  # solo l'estrazione


def candidate(text: str, duplicate_of=None, similar=()) -> dict:
    return {"text": text, "source": text, "duplicate_of": duplicate_of, "similar": list(similar)}


def test_store_saves_kept_ones_counts_duplicates_and_deletes_shown_ones():
    repository, morning_id = memory_with_morning()
    other_id = repository.add("fa la spesa il sabato", "x", unit(3))
    candidates = [
        candidate(EVENING, similar=[{"id": morning_id, "text": MORNING}]),
        candidate("legge prima di dormire"),
        candidate("la mattina studia meglio", duplicate_of=morning_id),
    ]
    # tiene solo la sera, cancella la mattina; l'id non mostrato e l'indice del duplicato
    # non contano
    answer = PreferencesResponse(keep=[0, 2], delete=[morning_id, other_id])

    result = store_preferences(candidates, answer, FakeEmbedder(), repository)

    assert sorted(repository.texts()) == sorted([EVENING, "fa la spesa il sabato"])
    assert result == {
        "saved": 1,
        "seen_again": 1,
        "deleted": 1,
        "message": "Preferenze: ricordate 1, già note 1, cancellate 1.",
    }


def test_store_with_nothing_kept_saves_nothing():
    repository = FakePreferenceRepository()
    embedder = FakeEmbedder()

    result = store_preferences(
        [candidate(EVENING)], PreferencesResponse(keep=[]), embedder, repository
    )

    assert repository.texts() == []
    assert result["message"] == ""
    assert embedder.calls == []  # niente da salvare: nessun embedding
