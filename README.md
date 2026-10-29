# FilmLog — Darkroom Film & Print Manager

A desktop catalogue for the hobbyist analog photographer who develops black &
white film and makes darkroom prints: **cameras**, **film rolls**, how each
roll was **developed**, and every **print** made from it. Built with Python,
PySide6 (Qt 6) and SQLite. Works fully offline.

- Rolls list with live search and filters (status, film, camera, developer,
  year, tag), push/pull badges and status chips.
- "Mark as developed" pre-fills the development from your last roll with the
  same film at the same EI, and a **past results** panel shows what worked
  before for the same film + developer + dilution.
- Print records with an ordered exposure table (single filter, split grade,
  dodge, burn, flash), total exposure time, and "Duplicate print" for the next
  attempt.
- Images (contact sheets, scans, print photos) copied into the app's data
  folder with thumbnails.
- Statistics, CSV/JSON export, JSON import, printable PDF "darkroom card".
- Follows your desktop's colours and light/dark mode by default (also on
  Sway/Hyprland/i3 via the GTK theme); Light, Dark and **Darkroom** themes
  (black background, dim red text; images shown as dim red monochrome) can be
  chosen in Settings. To use another Qt theme engine, set
  `QT_QPA_PLATFORMTHEME` yourself (e.g. `qt6ct`).

## Install

### Arch Linux

```sh
cd packaging/arch
makepkg -si
```

The package depends on the distro's `pyside6`, `python-sqlalchemy`,
`python-alembic` and `python-platformdirs`. Install `qt6-charts` to get charts
in the Statistics view (without it the numbers are shown as tables).

### Any distribution (from source)

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/):

```sh
uv sync            # creates .venv with runtime + dev dependencies
uv run filmlog     # or: uv run python -m filmlog
```

or install it for your user with `pipx install .` / `uv tool install .`.
To get a launcher entry, copy `packaging/filmlog.desktop` to
`~/.local/share/applications/` and the icons from `packaging/icons/hicolor/` to
`~/.local/share/icons/hicolor/`.

### Other packaging (notes)

- **Flatpak**: `packaging/flatpak/io.github.filmlog.FilmLog.yml` is a starting
  point using the KDE runtime and the `io.qt.PySide.BaseApp` base. Flatpak
  builds are offline, so generate `python3-deps.json` for SQLAlchemy, Alembic and
  platformdirs with `flatpak-pip-generator` first, and pick a real app id.
  Inside Flatpak the data lives in `~/.var/app/<app-id>/data/filmlog/`.
- **AppImage**: build a wheel (`uv build`), then bundle it with a Python
  runtime using e.g. `python-appimage` (`python-appimage build app`) or
  `appimage-builder`; add `packaging/filmlog.desktop` and the 256 px icon.
  PySide6 wheels from PyPI bundle Qt, so the AppImage runs on most
  glibc-based distributions.
- The app code uses no distro-specific paths or commands, so other native
  packages (deb/rpm) only need the same four runtime dependencies.

## Using FilmLog

| Shortcut | Action |
|---|---|
| `Ctrl+N` | New item in the current view |
| `Ctrl+F` | Search |
| `Ctrl+S` | Save the open form |
| `Esc` | Cancel / discard changes in the form |
| `Delete` | Delete the selected row (asks first) |
| `Ctrl+1` … `Ctrl+5` | Rolls, Prints, Cameras, Catalogue, Statistics |
| `Ctrl+P` | Export the selected roll as a PDF darkroom card |
| `Ctrl+,` | Settings (theme, °C/°F, cm/in) |

Times are typed as `90`, `1:30` or `1m30s` and shown as `m:ss`.

**Demo data**: *Help → Load demo data* adds example cameras, rolls and prints
(flagged as demo); *Help → Remove demo data* deletes them again. Development
times in the demo and seed data are common published starting points, not
recommendations.

## Where is my data?

| What | Location (Linux) |
|---|---|
| Database | `~/.local/share/filmlog/filmlog.db` |
| Attached images | `~/.local/share/filmlog/images/` (thumbnails in `images/.thumbs/`) |
| Automatic backups | `~/.local/share/filmlog/backups/` |
| Settings | `~/.config/filmlog/settings.json` |

Locations follow the XDG base-directory spec (`$XDG_DATA_HOME`,
`$XDG_CONFIG_HOME`). The `FILMLOG_DB` environment variable overrides the
database path; images and backups then live next to that file.

## Backup & restore

- **Automatic**: the database schema is migrated on start-up. Before any
  migration (and before a JSON import) the database is copied to
  `backups/filmlog-YYYYMMDD-HHMMSS.db`; the 10 newest are kept.
- **Manual**: *File → Back up database now…* writes a consistent copy wherever
  you like (safe while the app is running).
- **Restore**: quit FilmLog, copy the backup over `filmlog.db`. If you move to
  another machine, copy the `images/` folder too.
- **Export**: *File → Export to CSV* (one CSV per table, zipped) or *Export to
  JSON* (everything, nested). JSON exports can be merged into another FilmLog
  database with *File → Import JSON…* (rolls are matched by code; you choose
  Skip or Replace on conflicts). Image files are not inside exports — copy the
  `images/` folder separately.

## Development

```sh
FILMLOG_DB=/tmp/filmlog-dev.db uv run filmlog   # never touch your real data
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
uv run pytest
```

New schema change:
`FILMLOG_DB=/tmp/filmlog-dev.db uv run alembic revision --autogenerate -m "…"`
(review the generated file in `src/filmlog/db/migrations/versions/`).
After editing the SVG icon, regenerate the PNGs with
`uv run python packaging/icons/render_pngs.py`.

Design decisions taken during development are listed in
[`docs/decisions.md`](docs/decisions.md).

## Author

Written by **Pol Warnimont**, developed with the help of Claude (Anthropic).

## Licence

Copyright © 2026 Pol Warnimont.

FilmLog is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See [`LICENSE`](LICENSE).
