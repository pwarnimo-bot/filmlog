"""Database backups (online-safe copies via SQLite's backup API)."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

BACKUP_PREFIX = "filmlog-"
KEEP_BACKUPS = 10


def backup_database(src: Path, dest: Path) -> Path:
    """Copy the SQLite database ``src`` to ``dest`` consistently, even while open."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    source.close()
    target.close()
    return dest


def timestamped_backup(
    src: Path, backups_dir: Path, *, keep: int = KEEP_BACKUPS, now: dt.datetime | None = None
) -> Path:
    """Write ``backups/filmlog-YYYYMMDD-HHMMSS.db`` and prune to the newest ``keep``."""
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"{BACKUP_PREFIX}{stamp}.db"
    n = 1
    while dest.exists():
        dest = backups_dir / f"{BACKUP_PREFIX}{stamp}-{n}.db"
        n += 1
    backup_database(src, dest)
    prune_backups(backups_dir, keep=keep)
    return dest


def list_backups(backups_dir: Path) -> list[Path]:
    if not backups_dir.is_dir():
        return []
    return sorted(backups_dir.glob(f"{BACKUP_PREFIX}*.db"))


def prune_backups(backups_dir: Path, *, keep: int = KEEP_BACKUPS) -> list[Path]:
    backups = list_backups(backups_dir)
    removed = backups[:-keep] if keep > 0 else backups
    for p in removed:
        p.unlink(missing_ok=True)
    return removed
