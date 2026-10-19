"""crea task

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19 10:05:46.287007

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tasks table: the confirmed tasks of a day, with where the plan put them.

    The constraints repeat the rules of the Task model, so wrong data is rejected
    even if it does not come from the planner.
    """
    op.execute(
        """
        CREATE TABLE tasks (
            id                  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

            -- uno a molti: la chiave esterna sta dalla parte dei "molti";
            -- cancellando una giornata si cancellano anche i suoi task
            day_id              integer NOT NULL REFERENCES days (id) ON DELETE CASCADE,

            -- "t1", "t2": l'id del task dentro la giornata, come nel grafo
            task_key            text    NOT NULL,
            title               text    NOT NULL,
            source              text,   -- pezzo di frase da cui nasce il task (NULL se aggiunto dopo)

            duration_min        integer NOT NULL,
            priority            integer NOT NULL,
            required            boolean NOT NULL DEFAULT false,

            -- vincoli di orario, NULL = nessun vincolo
            fixed_start_min     integer,
            earliest_start_min  integer,
            deadline_min        integer,

            -- dove lo ha messo lo scheduler, NULL = non inserito nel piano
            scheduled_start_min integer,
            scheduled_end_min   integer,

            -- niente due "t1" nella stessa giornata; crea anche l'indice su (day_id, task_key),
            -- che serve alla query più frequente: "i task della giornata X"
            CONSTRAINT tasks_one_key_per_day UNIQUE (day_id, task_key),

            CONSTRAINT tasks_title_not_empty   CHECK (title <> ''),
            CONSTRAINT tasks_duration_in_range CHECK (duration_min BETWEEN 1 AND 720),
            CONSTRAINT tasks_priority_in_range CHECK (priority BETWEEN 1 AND 5),

            -- un CHECK su un valore NULL non fallisce: i vincoli assenti passano
            CONSTRAINT tasks_times_in_range CHECK (
                fixed_start_min    BETWEEN 0 AND 1440
                AND earliest_start_min BETWEEN 0 AND 1440
                AND deadline_min       BETWEEN 0 AND 1440
            ),
            -- le due regole di Task.check_window
            CONSTRAINT tasks_window_fits_duration CHECK (
                deadline_min - earliest_start_min >= duration_min
            ),
            CONSTRAINT tasks_fixed_start_before_deadline CHECK (
                fixed_start_min + duration_min <= deadline_min
            ),

            -- piano: inizio e fine entrambi presenti o entrambi assenti,
            -- e la durata nel piano è quella del task
            CONSTRAINT tasks_scheduled_both_or_none CHECK (
                (scheduled_start_min IS NULL) = (scheduled_end_min IS NULL)
            ),
            CONSTRAINT tasks_scheduled_matches_duration CHECK (
                scheduled_end_min - scheduled_start_min = duration_min
            )
        )
        """
    )


def downgrade() -> None:
    """Drop the tasks table."""
    op.execute("DROP TABLE tasks")
