import os

# Checkpoint in modalità strict: LangGraph deserializza solo i tipi dichiarati nello
# stato del grafo (Task, DayConfig...), e la modalità permissiva verrà rimossa.
# Va impostata prima che langgraph venga importato: conftest viene caricato per primo.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from planner.config import Settings

TEST_DB = "planner_test"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@pytest.fixture(scope="session")
def db_url() -> str:
    """URL of a separate test database, created if missing and migrated to the last revision.

    Runs once per test session. Tests that need the database are skipped if it is
    not reachable, so the rest of the suite runs without Docker.
    """
    main_url = Settings().database_url
    test_url = make_url(main_url).set(database=TEST_DB).render_as_string(hide_password=False)

    try:
        # CREATE DATABASE non può stare in una transazione: serve autocommit
        with psycopg.connect(main_url, autocommit=True, connect_timeout=3) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)
            ).fetchone()
            if not exists:
                # un nome di database non è un valore: si compone con sql.Identifier, non con %s
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    except psycopg.OperationalError:
        pytest.skip("database non raggiungibile: avvia Docker e `docker compose up -d`")

    # env.py di Alembic legge DATABASE_URL da Settings: la variabile d'ambiente
    # ha la precedenza sul file .env, quindi le migrazioni vanno sul database di test
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", test_url)
        command.upgrade(Config(toml_file=PYPROJECT), "head")
    return test_url


@pytest.fixture
def db(db_url: str):
    """A connection whose changes are all rolled back at the end of the test.

    Transactions opened inside the test become savepoints of this one,
    so every test starts from empty tables.
    """
    with psycopg.connect(db_url) as conn, conn.transaction(force_rollback=True):
        yield conn
