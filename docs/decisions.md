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

## Phase 2 — Data layer

- **Enums are stored as plain `VARCHAR(32)`** (no native enum, no CHECK
  constraint). Adding a value later needs no migration. Stable lowercase
  identifiers are stored; translated labels live in the UI.
- **Paper surfaces** gained `lustre` and `semi_matt` (seed papers use them).
  One `Paper` row per surface variant; display name is
  "Ilford Multigrade RC Deluxe (glossy)".
- **Film display name** is "Manufacturer Name ISO", but the ISO is not repeated
  when it already appears in the name ("Kodak Tri-X 400", not "… 400 400").
- **Water** is a built-in stop-bath `Chemical` row without manufacturer
  (`is_builtin = true`); it cannot be deleted.
- `Chemical.manufacturer_id` is nullable (needed for Water / home-brew).
- **All catalogue tables have `discontinued`** so in-use items can be retired
  instead of deleted.
- **Extra roll images**: a small `roll_image` table backs the Roll → Images tab
  (multiple scans per roll) in addition to the single `contact_sheet_image`.
- `Print.head_height_cm` is numeric (cm, shown in inches if selected);
  `aperture` is free text ("f/8").
- `is_demo` flag on cameras, rolls and prints (development / exposures go
  with their parents via cascade).
- Total print exposure **excludes dodge rows** (dodging happens during the base
  exposure); burns and flashes are added.
- **Session strategy**: the UI keeps one long-lived SQLAlchemy session
  (`expire_on_commit=False`). It's a single-user, single-process app; this keeps
  lazy loading simple. Forms only write to ORM objects on Save.
- Pre-migration backups use SQLite's online backup API, named
  `filmlog-YYYYMMDD-HHMMSS.db`; a brand-new empty DB is not backed up.
- Seed dilution strings are `;`-separated in `common_dilutions`.
- "Kodak/Harman Selenium toner" is seeded as *Kodak Selenium Toner* with a note.
  "Adox Adonal / R09 One Shot" is one entry with that name.

## Phase 3 — Cameras & Catalogue UI

- Generic **list + editor** pattern (`ListDetailPanel` + `EditorForm`) used by
  every CRUD screen: searchable `ObjectTable` (model/view with a
  `QSortFilterProxyModel`) on the left, form on the right.
- Switching rows / creating a new item with unsaved changes asks
  Save / Discard / Cancel (a confirmation, not an error popup).
- Catalogue delete rule: in-use items can't be deleted; the dialog offers
  "Mark as discontinued" instead. Discontinued items are greyed in lists and
  hidden from dropdowns for new records (still shown on existing ones).
- Deleting a camera that has rolls is allowed after a warning (rolls keep their
  data, camera link becomes empty); the warning suggests Retired/Sold status.
- The live search matches **all words** anywhere in the visible row.
- Right-click a table header to show/hide columns; widths, order, visibility and
  sort are remembered per table.
- Empty optional numbers/dates show "—" (spin box minimum / special date);
  press Delete/Backspace on a date's first section to clear it.

## Phase 4 — Rolls & Development UI

- **Push/pull** is recalculated whenever the EI or film changes; the user can
  then override it with the ⅓-stop spin box. Changing the film also moves the EI
  to the new box speed unless the user had typed a different EI.
- **Status flow**: the status combo offers loaded / exposed / developed. A roll
  with a development record cannot be moved back out of "developed" (inline
  hint); "Delete development" on the Development tab resets it to "exposed".
- **Mark as developed** saves pending roll edits first, then opens a *new,
  unsaved* development pre-filled per the spec (same film + EI → same film →
  last). Saving it links it to the roll and sets status = developed; Cancel
  leaves the roll untouched.
- Pre-fill copies chemistry, dilutions, times, agitation and tank — not the
  date (today), rating, notes or "developed with".
- **Past results** panel: same film + developer, and by default the same
  dilution (checkbox to widen). "Use selected" (or double-click) copies
  dilution, time, temperature and agitation into the form. A caption reminds
  that published times are only starting points.
- "Developed with" is entered as comma-separated roll codes (with completion)
  and validated inline.
- Roll filters: status, film (only films that have rolls), camera, developer,
  year, tag. "Year" is taken from the load/finish/develop date, else from a
  `YYYY-` code prefix.
- Selecting a new camera sets the roll's format from the camera, and if the
  camera lists exactly one lens it pre-fills the lens.
- Tags are case-insensitive and unused tags are pruned on save/delete.
