"""Integration tests for the preferences table (pgvector). Each test is rolled back."""

import math
from datetime import timedelta

import psycopg
import pytest

from planner.db.preferences import (
    delete_preference,
    insert_preference,
    list_preferences,
    mark_seen,
    similar_preferences,
)
from planner.llm.embedder import EMBED_DIM
from tests.fakes import unit


def between(i: int, j: int, cos: float) -> list[float]:
    """A unit vector whose cosine similarity with unit(i) is `cos`, on the plane of axes i and j."""
    vector = [0.0] * EMBED_DIM
    vector[i], vector[j] = cos, math.sqrt(1 - cos * cos)
    return vector


def add(conn, text: str, embedding: list[float]) -> int:
    return insert_preference(conn, text, f"«{text}»", embedding)


def test_inserted_preference_is_listed_with_defaults(db):
    pref_id = add(db, "preferisce studiare la mattina", unit(1))

    (saved,) = list_preferences(db)

    today = db.execute("SELECT current_date").fetchone()[0]
    assert saved.id == pref_id
    assert (saved.text, saved.source) == (
        "preferisce studiare la mattina",
        "«preferisce studiare la mattina»",
    )
    assert (saved.times_seen, saved.first_seen, saved.last_seen) == (1, today, today)


def test_similar_preferences_are_the_close_ones_closest_first(db):
    add(db, "molto vicina", between(1, 2, 0.95))
    add(db, "vicina", between(1, 3, 0.88))
    add(db, "lontana", between(1, 4, 0.50))

    found = similar_preferences(db, unit(1), min_similarity=0.85)

    assert [p.text for p in found] == ["molto vicina", "vicina"]  # la lontana è sotto soglia
    assert [round(p.similarity, 2) for p in found] == [0.95, 0.88]


def test_similar_preferences_respects_the_limit(db):
    for k in range(5):
        add(db, f"p{k}", between(1, 2 + k, 0.9 + k / 100))

    assert len(similar_preferences(db, unit(1), min_similarity=0.85, limit=3)) == 3


def test_no_similar_preferences_in_an_empty_table(db):
    assert similar_preferences(db, unit(1), min_similarity=0.0) == []


def test_mark_seen_counts_and_updates_last_seen(db):
    pref_id = add(db, "palestra la sera", unit(1))
    week_ago = db.execute("SELECT current_date - 7").fetchone()[0]
    db.execute(
        "UPDATE preferences SET first_seen = %s, last_seen = %s WHERE id = %s",
        (week_ago, week_ago, pref_id),
    )

    mark_seen(db, pref_id)
    mark_seen(db, pref_id)

    (saved,) = list_preferences(db)
    assert saved.times_seen == 3
    assert saved.first_seen == week_ago
    assert saved.last_seen == week_ago + timedelta(7)


def test_delete_preference(db):
    pref_id = add(db, "spesa il sabato", unit(1))

    assert delete_preference(db, pref_id) is True
    assert delete_preference(db, pref_id) is False  # non c'è più
    assert list_preferences(db) == []


def test_list_is_ordered_by_last_seen(db):
    old = add(db, "vecchia", unit(1))
    add(db, "recente", unit(2))
    db.execute(
        "UPDATE preferences SET first_seen = current_date - 3, last_seen = current_date - 3 "
        "WHERE id = %s",
        (old,),
    )

    assert [p.text for p in list_preferences(db)] == ["recente", "vecchia"]


def test_vector_of_the_wrong_size_is_rejected_by_the_database(db):
    with pytest.raises(psycopg.errors.DataException, match="768 dimensions"):
        insert_preference(db, "x", "x", [1.0, 0.0, 0.0])


def test_preferences_survive_the_purge_of_old_days(db):
    # nessun legame con days: la pulizia delle giornate non le tocca
    add(db, "preferisce studiare la mattina", unit(1))
    db.execute(
        "INSERT INTO days (day_date, user_input, day_start_min, day_end_min) "
        "VALUES (current_date - 30, 'vecchia', 480, 1320)"
    )

    db.execute("CALL purge_old_days()")

    assert db.execute("SELECT count(*) FROM days").fetchone() == (0,)
    assert [p.text for p in list_preferences(db)] == ["preferisce studiare la mattina"]
