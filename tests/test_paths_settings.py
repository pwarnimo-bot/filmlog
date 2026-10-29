# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from pathlib import Path

from filmlog import paths
from filmlog.services.settings import Settings


def test_db_path_env_override(isolated_paths: Path) -> None:
    assert paths.db_path() == (isolated_paths / "data" / "filmlog.db").resolve()
    assert paths.images_dir() == paths.data_dir() / "images"
    assert paths.backups_dir() == paths.data_dir() / "backups"


def test_ensure_dirs_creates_tree() -> None:
    paths.ensure_dirs()
    assert paths.images_dir().is_dir()
    assert paths.backups_dir().is_dir()
    assert paths.config_dir().is_dir()


def test_settings_roundtrip() -> None:
    s = Settings.load()
    assert s.theme == "system"
    s.theme = "darkroom"
    s.temperature_unit = "F"
    s.table_states["rolls"] = "abc"
    s.save()
    again = Settings.load()
    assert again.theme == "darkroom"
    assert again.temperature_unit == "F"
    assert again.table_states == {"rolls": "abc"}


def test_settings_tolerates_garbage() -> None:
    paths.config_dir().mkdir(parents=True, exist_ok=True)
    paths.config_file().write_text('{"theme": "neon", "unknown": 1}')
    s = Settings.load()
    assert s.theme == "system"
