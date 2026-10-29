"""Run Alembic migrations at start-up, backing up the DB first."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from filmlog.services.backup import timestamped_backup

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    return cfg


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def head_revision(engine: Engine) -> str | None:
    return ScriptDirectory.from_config(alembic_config(engine)).get_current_head()


def needs_migration(engine: Engine) -> bool:
    return current_revision(engine) != head_revision(engine)


def _has_user_tables(engine: Engine) -> bool:
    from sqlalchemy import inspect

    return bool(inspect(engine).get_table_names())


def upgrade(engine: Engine, db_file: Path | None, backups_dir: Path | None) -> Path | None:
    """Upgrade to head. Returns the backup path if a backup was taken."""
    if not needs_migration(engine):
        return None
    backup: Path | None = None
    if (
        db_file is not None
        and backups_dir is not None
        and db_file.exists()
        and _has_user_tables(engine)
    ):
        engine.dispose()
        backup = timestamped_backup(db_file, backups_dir)
    cfg = alembic_config(engine)
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    return backup
