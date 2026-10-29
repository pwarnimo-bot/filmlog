from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from filmlog import paths
from filmlog.db.database import Database, open_database
from filmlog.db.enums import ChemicalKind
from filmlog.db.migrate import current_revision, head_revision
from filmlog.db.models import AgitationPreset, Chemical, FilmStock, Manufacturer, Paper
from filmlog.seed.loader import ensure_catalogue_seeded, load_catalogue, read_seed
from filmlog.services.backup import prune_backups, timestamped_backup
from tests.factories import film


def test_fresh_db_is_migrated_and_seeded(db: Database, session: Session) -> None:
    assert db.seeded
    assert db.backup_taken is None  # nothing to back up on a brand-new DB
    assert current_revision(db.engine) == head_revision(db.engine)
    data = read_seed("catalogue.json")
    assert session.scalar(select(func.count()).select_from(FilmStock)) == len(data["film_stocks"])
    assert session.scalar(select(func.count()).select_from(Chemical)) == len(data["chemicals"])
    assert session.scalar(select(func.count()).select_from(Paper)) == len(data["papers"])
    assert session.scalar(select(func.count()).select_from(AgitationPreset)) == 6


def test_seed_is_idempotent(session: Session) -> None:
    counts = load_catalogue(session)
    assert all(v == 0 for v in counts.values())
    assert not ensure_catalogue_seeded(session)


def test_display_names(session: Session) -> None:
    assert film(session, "FP4 Plus").display_name == "Ilford FP4 Plus 125"
    assert film(session, "Tri-X 400").display_name == "Kodak Tri-X 400"
    assert film(session, "Fomapan 100 Classic").display_name == "Foma Fomapan 100 Classic"
    assert film(session, "Ektapan 400").aliases == "T-Max 400"


def test_water_is_builtin_stop(session: Session) -> None:
    water = session.scalar(select(Chemical).where(Chemical.name == "Water"))
    assert water is not None
    assert water.is_builtin and water.kind == ChemicalKind.STOP_BATH
    assert water.manufacturer is None
    assert water.display_name == "Water"


def test_reopen_existing_db_does_not_reseed_or_backup(db: Database) -> None:
    db.engine.dispose()
    again = open_database(paths.db_path(), paths.backups_dir())
    assert not again.seeded
    assert again.backup_taken is None
    with again.session() as s:
        assert s.scalar(select(func.count()).select_from(Manufacturer)) == 12
    again.engine.dispose()


def test_backup_taken_before_migration(isolated_paths: Path) -> None:
    db_file = paths.db_path()
    db_file.parent.mkdir(parents=True)
    # An old database with user data but no alembic version → needs migration.
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE legacy (x INTEGER)")
        conn.execute("INSERT INTO legacy VALUES (1)")
    conn.close()
    database = open_database(db_file, paths.backups_dir())
    assert database.backup_taken is not None
    assert database.backup_taken.exists()
    with sqlite3.connect(database.backup_taken) as b:
        assert b.execute("SELECT x FROM legacy").fetchone() == (1,)
    b.close()
    database.engine.dispose()


def test_backup_rotation_keeps_last_ten(tmp_path: Path) -> None:
    src = tmp_path / "x.db"
    with sqlite3.connect(src) as c:
        c.execute("CREATE TABLE t (x)")
    c.close()
    import datetime as dt

    base = dt.datetime(2026, 1, 1, 12, 0, 0)
    for i in range(13):
        timestamped_backup(src, tmp_path / "b", now=base + dt.timedelta(minutes=i))
    names = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert len(names) == 10
    assert names[0] == "filmlog-20260101-120300.db"
    assert prune_backups(tmp_path / "b", keep=10) == []
