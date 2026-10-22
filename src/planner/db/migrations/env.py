from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from planner.config import Settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# indirizzo del database: quello passato da upgrade_database (API all'avvio, test), altrimenti
# quello di .env, come nel resto del progetto (non da alembic.ini).
# "postgresql://" per SQLAlchemy vuol dire psycopg2: il driver va cambiato in psycopg 3.
url = config.attributes.get("database_url") or Settings().database_url
db_url = make_url(url).set(drivername="postgresql+psycopg")
config.set_main_option("sqlalchemy.url", db_url.render_as_string(hide_password=False))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,  # un BEGIN/COMMIT per revisione anche nello script SQL
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # una transazione per revisione: se la 0003 fallisce, 0001 e 0002 restano
            # applicate e alembic_version resta coerente con lo schema
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
