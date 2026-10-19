import json

import pytest
from pydantic import ValidationError

from planner.agents.preferences import (
    ExtractedPreferences,
    PreferenceDraft,
    SameVerdict,
    extract_preferences,
    same_preference,
)
from tests.fakes import FakeClient


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
