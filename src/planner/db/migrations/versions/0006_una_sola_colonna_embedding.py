"""una sola colonna embedding

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop cluster_embedding: duplicates now use the same vector as retrieval.

    A new preference is embedded as a query and compared with the saved documents.
    Measured on the same pairs, query/document separates the candidates from the
    unrelated preferences better than clustering/clustering (tests/eval/run_embeddings.py).
    """
    op.execute("ALTER TABLE preferences DROP COLUMN cluster_embedding")


def downgrade() -> None:
    """Add cluster_embedding back, filled with the document vectors.

    The original clustering vectors are lost: a copy keeps the column valid (NOT NULL),
    and the preferences can be re-embedded if that revision is ever used again.
    """
    op.execute("ALTER TABLE preferences ADD COLUMN cluster_embedding vector(768)")
    op.execute("UPDATE preferences SET cluster_embedding = embedding")
    op.execute("ALTER TABLE preferences ALTER COLUMN cluster_embedding SET NOT NULL")
