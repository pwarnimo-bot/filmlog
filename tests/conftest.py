from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Never touch the real user data: point DB and config at a temp dir."""
    monkeypatch.setenv("FILMLOG_DB", str(tmp_path / "data" / "filmlog.db"))
    monkeypatch.setenv("FILMLOG_CONFIG_DIR", str(tmp_path / "config"))
    yield tmp_path


@pytest.fixture
def db(isolated_paths: Path):  # type: ignore[no-untyped-def]
    from filmlog import paths
    from filmlog.db.database import open_database

    database = open_database(paths.db_path(), paths.backups_dir())
    yield database
    database.engine.dispose()


@pytest.fixture
def session(db):  # type: ignore[no-untyped-def]
    with db.session() as s:
        yield s
