"""Alembic environment.

At runtime ``filmlog.db.migrate`` passes an open connection via
``config.attributes["connection"]``. From the command line (``alembic ...``)
the URL comes from ``FILMLOG_DB`` / the default data path.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from filmlog import paths
from filmlog.db.engine import make_engine
from filmlog.db.models import Base

config = context.config
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = config.get_main_option("sqlalchemy.url")
    engine = make_engine(url.removeprefix("sqlite:///") if url else paths.db_path())
    with engine.begin() as conn:
        _run(conn)


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported.")
run_migrations_online()
