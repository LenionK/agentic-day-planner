"""vista riepilogo giornate

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19 16:44:29.055840

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create day_summary: one row per saved day, with how full it is.

    A view stores no data: every SELECT runs the query on the tables, so it is always
    up to date, and every client (Python, psql, VS Code) gets the same numbers.
    """
    op.execute(
        """
        CREATE VIEW day_summary AS
        SELECT
            d.id,
            d.day_date,
            -- giorno della settimana ISO: 1 = lunedì ... 7 = domenica
            extract(isodow FROM d.day_date)::integer             AS weekday,
            d.user_input,
            d.day_end_min - d.day_start_min                      AS day_minutes,
            count(t.id)::integer                                 AS task_count,
            count(t.id) FILTER (WHERE t.required)::integer       AS required_count,
            -- coalesce: una giornata senza task ha somma NULL, non 0
            coalesce(sum(t.scheduled_end_min - t.scheduled_start_min), 0)::integer
                                                                 AS busy_minutes,
            round(
                100.0 * coalesce(sum(t.scheduled_end_min - t.scheduled_start_min), 0)
                / (d.day_end_min - d.day_start_min)
            )::integer                                           AS busy_percent,
            min(t.scheduled_start_min)                           AS first_start_min,
            max(t.scheduled_end_min)                             AS last_end_min
        FROM days d
        -- LEFT JOIN: le giornate senza task restano, con conteggi a zero
        LEFT JOIN tasks t ON t.day_id = d.id
        -- basta raggruppare per la chiave primaria: le altre colonne di days
        -- dipendono da lei, e PostgreSQL permette di selezionarle
        GROUP BY d.id
        """
    )


def downgrade() -> None:
    """Drop the day_summary view (the tables are not touched)."""
    op.execute("DROP VIEW day_summary")
