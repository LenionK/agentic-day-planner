"""Bring the database schema to the last Alembic revision, from Python.

The API calls it at startup and the tests on their own database: nobody has to remember
`alembic upgrade head`. On an up-to-date database it changes nothing.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

# la configurazione di Alembic sta in [tool.alembic] di pyproject.toml, nella radice del progetto
PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


def upgrade_database(url: str) -> None:
    """Apply the missing revisions to the database at `url` (alembic upgrade head)."""
    config = Config(toml_file=str(PYPROJECT))
    # l'indirizzo arriva a env.py come attributo: niente variabili d'ambiente da cambiare
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
