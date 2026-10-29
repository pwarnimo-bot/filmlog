# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Filesystem locations (XDG-correct via platformdirs).

The database location can be overridden with the ``FILMLOG_DB`` environment
variable; images and backups always live next to the database file. The config
directory can be overridden with ``FILMLOG_CONFIG_DIR`` (used by tests).
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "filmlog"


def db_path() -> Path:
    override = os.environ.get("FILMLOG_DB")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_data_dir(APP_NAME)) / "filmlog.db"


def data_dir() -> Path:
    return db_path().parent


def images_dir() -> Path:
    return data_dir() / "images"


def thumbnails_dir() -> Path:
    return images_dir() / ".thumbs"


def backups_dir() -> Path:
    return data_dir() / "backups"


def config_dir() -> Path:
    override = os.environ.get("FILMLOG_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path(user_config_dir(APP_NAME))


def config_file() -> Path:
    return config_dir() / "settings.json"


def ensure_dirs() -> None:
    for d in (data_dir(), images_dir(), thumbnails_dir(), backups_dir(), config_dir()):
        d.mkdir(parents=True, exist_ok=True)
