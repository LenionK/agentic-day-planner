"""Save, find and delete user preferences in PostgreSQL with pgvector.

Like store.py, the functions receive an open connection. Vectors travel as Python lists
of floats and are cast with ::vector in the SQL: psycopg sends a list as a float array,
and pgvector converts arrays to vectors.
"""

from datetime import date

import psycopg
from psycopg.rows import class_row
from pydantic import BaseModel


class SavedPreference(BaseModel):
    """A preference as shown to the user (the vectors stay in the database)."""

    id: int
    text: str
    source: str
    times_seen: int
    first_seen: date
    last_seen: date


class SimilarPreference(BaseModel):
    id: int
    text: str
    similarity: float  # 1 - distanza coseno: 1 = stesso significato


def insert_preference(
    conn: psycopg.Connection,
    text: str,
    source: str,
    embedding: list[float],
    cluster_embedding: list[float],
) -> int:
    """Save a new preference, seen once today; return its id."""
    (pref_id,) = conn.execute(
        """
        INSERT INTO preferences (text, source, embedding, cluster_embedding)
        VALUES (%s, %s, %s::vector, %s::vector)
        RETURNING id
        """,
        (text, source, embedding, cluster_embedding),
    ).fetchone()
    return pref_id


def similar_preferences(
    conn: psycopg.Connection, cluster_embedding: list[float], min_similarity: float, limit: int = 3
) -> list[SimilarPreference]:
    """Saved preferences close to this one (clustering vectors), the closest first.

    Only candidates: being close does not mean saying the same thing ("studiare la mattina"
    and "la sera" are very close). The judge or the user decides.
    """
    with conn.cursor(row_factory=class_row(SimilarPreference)) as cur:
        cur.execute(
            """
            SELECT id, text, 1 - (cluster_embedding <=> %(vec)s::vector) AS similarity
            FROM preferences
            WHERE 1 - (cluster_embedding <=> %(vec)s::vector) >= %(min)s
            ORDER BY cluster_embedding <=> %(vec)s::vector
            LIMIT %(limit)s
            """,
            {"vec": cluster_embedding, "min": min_similarity, "limit": limit},
        )
        return cur.fetchall()


def mark_seen(conn: psycopg.Connection, pref_id: int) -> None:
    """The user expressed this preference again: one more time, seen today."""
    conn.execute(
        """
        UPDATE preferences
        SET times_seen = times_seen + 1, last_seen = greatest(last_seen, current_date)
        WHERE id = %s
        """,
        (pref_id,),
    )


def delete_preference(conn: psycopg.Connection, pref_id: int) -> bool:
    """Delete a preference; False if it did not exist."""
    return conn.execute("DELETE FROM preferences WHERE id = %s", (pref_id,)).rowcount == 1


def list_preferences(conn: psycopg.Connection) -> list[SavedPreference]:
    """All saved preferences, the most recently seen first."""
    with conn.cursor(row_factory=class_row(SavedPreference)) as cur:
        cur.execute(
            """
            SELECT id, text, source, times_seen, first_seen, last_seen
            FROM preferences
            ORDER BY last_seen DESC, times_seen DESC, id
            """
        )
        return cur.fetchall()
