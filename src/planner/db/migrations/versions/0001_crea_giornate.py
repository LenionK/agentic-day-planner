"""crea giornate

Revision ID: 0001
Revises:
Create Date: 2026-10-19 09:52:21.570826

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the days table: one row per date.

    Planning a date again is an overwrite, which the application asks the user about;
    the UNIQUE constraint is the last line of defence.
    """
    op.execute(
        """
        CREATE TABLE days (
            -- chiave primaria generata dal database: 1, 2, 3...
            -- ALWAYS: un INSERT non può impostarla a mano (BY DEFAULT lo permetterebbe)
            id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

            day_date      date        NOT NULL,
            user_input    text        NOT NULL,

            -- minuti dalla mezzanotte, come DayConfig in Python
            day_start_min integer     NOT NULL,
            day_end_min   integer     NOT NULL,

            -- istante di creazione, in UTC; mostrato nel fuso orario della sessione
            created_at    timestamptz NOT NULL DEFAULT now(),

            -- vincoli con un nome: quando un INSERT viene rifiutato, l'errore lo cita
            -- una sola giornata per data (crea anche un indice su day_date)
            CONSTRAINT days_one_per_date    UNIQUE (day_date),
            CONSTRAINT days_start_in_range  CHECK (day_start_min BETWEEN 0 AND 1440),
            CONSTRAINT days_end_in_range    CHECK (day_end_min BETWEEN 0 AND 1440),
            CONSTRAINT days_end_after_start CHECK (day_end_min > day_start_min)
        )
        """
    )


def downgrade() -> None:
    """Drop the days table."""
    op.execute("DROP TABLE days")
