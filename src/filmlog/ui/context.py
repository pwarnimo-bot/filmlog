"""Shared state handed to every view: settings and the DB session."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from filmlog.db.database import Database
from filmlog.services.settings import Settings


@dataclass
class AppContext:
    settings: Settings
    db: Database
    # One long-lived session for the UI (single-user desktop app, single process).
    session: Session = field(init=False)

    def __post_init__(self) -> None:
        self.session = self.db.session()
