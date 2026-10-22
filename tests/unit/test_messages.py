import pytest

from planner.messages import LANGUAGES, MESSAGES, placeholders, say


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_every_message_has_every_language_with_the_same_placeholders(key):
    texts = MESSAGES[key]

    assert set(texts) == set(LANGUAGES)
    # un segnaposto dimenticato in una lingua sarebbe un KeyError solo con quella lingua
    assert placeholders(texts["it"]) == placeholders(texts["en"])


def test_say_fills_the_placeholders_in_the_language_asked():
    values = {"title": "Corsa", "minutes": 90}

    assert say("suggestion_does_not_fit", "en", **values) == (
        "Suggestion dropped: Corsa (90 min) does not fit in any free slot"
    )
    assert say("suggestion_does_not_fit", "it", **values) == (
        "Proposta scartata: Corsa (90 min) non entra in nessun intervallo libero"
    )


def test_italian_is_the_default():
    assert say("save_new") == "Piano salvato."


def test_placeholders_lists_the_names_between_braces():
    assert placeholders("{title}: {field} {value} ignored") == {"title", "field", "value"}
