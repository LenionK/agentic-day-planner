"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

from collections.abc import Sequence

from alembic import op
${imports if imports else ""}
# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision).replace("'", '"')}
down_revision: str | Sequence[str] | None = ${repr(down_revision).replace("'", '"')}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels).replace("'", '"')}
depends_on: str | Sequence[str] | None = ${repr(depends_on).replace("'", '"')}


def upgrade() -> None:
    """Upgrade schema."""
    # SQL puro: op.execute("""...""")
    ${upgrades if upgrades else ""}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else ""}
