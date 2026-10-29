# FilmLog — Darkroom Film & Print Manager

A desktop catalogue for the hobbyist analog photographer: cameras, film rolls,
development records and darkroom prints. Built with Python, PySide6 (Qt 6) and
SQLite. Works fully offline.

## Run from source (development)

Requires Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync                    # creates .venv with runtime + dev dependencies
uv run filmlog             # or: uv run python -m filmlog
```

During development, keep your real data safe by pointing the app at a scratch
database:

```sh
FILMLOG_DB=/tmp/filmlog-dev.db uv run filmlog
```

Checks:

```sh
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest
```

## Where is my data?

| What | Location (Linux) |
|---|---|
| Database | `~/.local/share/filmlog/filmlog.db` |
| Attached images | `~/.local/share/filmlog/images/` |
| Automatic backups | `~/.local/share/filmlog/backups/` |
| Settings | `~/.config/filmlog/settings.json` |

Locations follow the XDG base-directory spec (`$XDG_DATA_HOME`,
`$XDG_CONFIG_HOME`). `FILMLOG_DB` overrides the database path; images and
backups then live next to that file.

## Backup & restore

- The database is migrated automatically on start-up. **Before any migration**
  the database is copied to `backups/filmlog-YYYYMMDD-HHMMSS.db` (the last 10
  are kept).
- To restore, quit FilmLog and copy a backup over `filmlog.db`. Copy the
  `images/` folder too if you moved machines.
