# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Engine and session factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def _enable_foreign_keys(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def make_engine(path: Path | str) -> Engine:
    url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{path}"
    engine = create_engine(url)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: the UI keeps objects around after saving.
    return sessionmaker(bind=engine, expire_on_commit=False)
