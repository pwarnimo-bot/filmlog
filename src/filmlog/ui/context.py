"""Shared state handed to every view: settings and (later) the DB session."""

from __future__ import annotations

from dataclasses import dataclass

from filmlog.services.settings import Settings


@dataclass
class AppContext:
    settings: Settings
