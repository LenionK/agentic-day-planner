"""tabella preferenze

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19 20:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Enable pgvector and create the preferences table.

    No foreign key to days: a preference outlives the day it came from, so the purge
    of old days does not touch it. One vector per preference, embedded as a document:
    new preferences (duplicates) and the tasks of a new day (retrieval) search it as
    queries. 768 must match EMBED_DIM in planner.llm.embedder.
    """
    # l'estensione è installata nell'immagine pgvector/pgvector, va solo attivata nel database
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE preferences (
            id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            text       text        NOT NULL,
            source     text        NOT NULL,   -- il pezzo di frase da cui è nata
            embedding  vector(768) NOT NULL,   -- prefisso search_document
            times_seen integer     NOT NULL DEFAULT 1,
            first_seen date        NOT NULL DEFAULT current_date,
            last_seen  date        NOT NULL DEFAULT current_date,

            CONSTRAINT preferences_text_not_empty CHECK (text <> ''),
            CONSTRAINT preferences_seen_at_least_once CHECK (times_seen >= 1),
            CONSTRAINT preferences_seen_in_order CHECK (last_seen >= first_seen)
        )
        """
    )
    # niente indice HNSW: con poche decine di preferenze il confronto completo è istantaneo


def downgrade() -> None:
    """Drop the preferences table and disable pgvector."""
    op.execute("DROP TABLE preferences")
    op.execute("DROP EXTENSION IF EXISTS vector")
