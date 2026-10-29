# Design decisions

Small decisions taken where CLAUDE.md was ambiguous. Newest at the bottom of
each phase.

## Phase 1 — Skeleton

- **Project root**: the repository root *is* the `filmlog/` folder from the
  layout in CLAUDE.md (pyproject, `src/filmlog`, `tests`, …).
- **Entry point**: a single `filmlog` entry point declared under
  `[project.gui-scripts]`. On Linux gui-scripts behave exactly like console
  scripts (output still goes to the terminal), so one name serves both.
- **Build backend**: hatchling (build-time only; not a runtime dependency).
- **"Follow system" theme** keeps the platform's Qt style and palette (Breeze on
  KDE, the GNOME/Adwaita palette elsewhere) for a native look. Light, Dark and
  Darkroom switch to the Fusion style with explicit palettes so they look the
  same on every desktop.
- **Settings** live in `settings.json` in the config dir (plain JSON, written
  atomically) rather than `QSettings`, so the services layer can read them
  without Qt. Window geometry / table header states are stored base64-encoded.
- `Esc` and `Delete` are bound per widget (forms / tables) rather than
  window-wide, so they don't interfere with text editing.
- Extra shortcuts: `Ctrl+1…5` switch sidebar views, `Ctrl+,` opens Settings.
