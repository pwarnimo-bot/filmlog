"""Open the application database: migrate (with backup) and seed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from filmlog.db.engine import make_engine, make_session_factory
from filmlog.db.migrate import upgrade
from filmlog.seed.loader import ensure_catalogue_seeded


@dataclass
class Database:
    path: Path
    engine: Engine
    session_factory: sessionmaker[Session]
    backup_taken: Path | None = None
    seeded: bool = False

    def session(self) -> Session:
        return self.session_factory()


def open_database(db_file: Path, backups_dir: Path, *, seed: bool = True) -> Database:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(db_file)
    backup = upgrade(engine, db_file, backups_dir)
    factory = make_session_factory(engine)
    seeded = False
    if seed:
        with factory() as s:
            seeded = ensure_catalogue_seeded(s)
    return Database(db_file, engine, factory, backup, seeded)
