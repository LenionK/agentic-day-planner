import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from planner.config import Settings
from planner.db.migrate import upgrade_database

EMPTY_DB = "planner_migrate_test"


@pytest.fixture
def empty_db_url(db_url):
    """A brand-new database with no tables, dropped at the end.

    It asks for db_url only to share its rule: without the database the test is skipped,
    or fails with REQUIRE_DATABASE=1 (in CI).
    """
    main_url = Settings().database_url
    admin = psycopg.connect(main_url, autocommit=True, connect_timeout=3)
    name = sql.Identifier(EMPTY_DB)
    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(name))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(name))
        yield make_url(main_url).set(database=EMPTY_DB).render_as_string(hide_password=False)
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(name))


def tables(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    return {name for (name,) in rows}


def test_an_empty_database_gets_every_table_and_upgrading_again_changes_nothing(empty_db_url):
    assert tables(empty_db_url) == set()

    upgrade_database(empty_db_url)
    after_first = tables(empty_db_url)
    upgrade_database(empty_db_url)  # già all'ultima revisione: niente da fare, nessun errore

    assert {"days", "tasks", "preferences", "alembic_version"} <= after_first
    assert tables(empty_db_url) == after_first
    with psycopg.connect(empty_db_url) as conn:
        (version,) = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version.startswith("0005")
