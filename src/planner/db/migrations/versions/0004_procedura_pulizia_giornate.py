"""procedura pulizia giornate

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19 18:05:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create purge_old_days: delete the days older than keep_days (their tasks go too).

    A PROCEDURE runs an operation and returns nothing; it is invoked with CALL.
    The rule "how long to keep" lives here, the same for every client.
    """
    # current_date - keep_days è una DATA, non un numero: la soglia. PostgreSQL conta i
    # giorni del calendario, anche tra mesi e anni diversi. Esempio con keep_days = 14:
    # oggi 10/11 -> soglia 27/10; il 19/10 (22 giorni prima) si cancella, il 27/10 resta.
    op.execute(
        """
        CREATE PROCEDURE purge_old_days(keep_days integer DEFAULT 14)
        LANGUAGE sql
        AS $$
            -- data meno intero = la data di N giorni prima; "<": il giorno esatto resta.
            -- I task vanno via con ON DELETE CASCADE; le giornate future non si toccano
            DELETE FROM days WHERE day_date < current_date - keep_days;
        $$
        """
    )


def downgrade() -> None:
    """Drop the purge_old_days procedure (the tables are not touched)."""
    op.execute("DROP PROCEDURE purge_old_days(integer)")
