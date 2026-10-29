# FilmLog — Darkroom Film & Print Manager

## What we are building

A desktop application for a hobbyist analog photographer who develops their own black-and-white film and makes darkroom prints. The app is a personal catalogue of:

- **Cameras** the photographer owns/uses
- **Film rolls** (one record per roll or sheet batch), including which camera shot them
- **Development** records for each roll (how it was developed)
- **Prints** made from each roll (how each print was exposed and processed)

It must look good, be fast to enter data into (darkroom notes are often typed up from scribbled paper afterwards), and make it easy to browse the collection and reuse past "recipes".

Primary platform: **Arch Linux** (Wayland and X11). It must also run on other Linux distributions later without code changes, so avoid anything Arch-specific in the code itself.

---

## Tech stack (decided — do not change without asking)

| Concern | Choice | Why |
|---|---|---|
| Language | Python ≥ 3.12 | Available on every distro, easy to maintain |
| GUI | **PySide6** (Qt 6, LGPL) | Native-looking on KDE/GNOME, Wayland + X11, good tables/forms |
| Database | **SQLite** (single file) | Zero setup, easy to back up |
| ORM / migrations | SQLAlchemy 2.x (typed `Mapped[]` style) + Alembic | Schema will evolve; migrations protect the user's data |
| Paths | `platformdirs` | XDG-correct locations on any distro |
| Tests | pytest (+ pytest-qt for a few UI smoke tests) | |
| Env / tooling | `uv` for dev, `ruff` for lint/format, `mypy` (non-strict) | |
| Packaging | `pyproject.toml` with console + gui entry point `filmlog` | Later: PKGBUILD, Flatpak, AppImage |

Rules:
- No network access at runtime. Everything works offline.
- No distro-specific calls (no `pacman`, no hardcoded `/usr/...` paths in app code).
- Data file: `platformdirs.user_data_dir("filmlog")/filmlog.db` (i.e. `~/.local/share/filmlog/` on Linux). Attached images go in an `images/` folder next to it. Config (window size, theme, units) in `user_config_dir("filmlog")`.
- On startup, run Alembic migrations automatically; **before any migration, copy the DB to a timestamped backup** in `backups/` (keep the last 10).

---

## Data model

All times are stored as **integer seconds** and entered/displayed as `m:ss` (accept `90`, `1:30`, `1m30s`). Temperatures stored in °C (display can switch to °F in settings). Every table has `id`, `created_at`, `updated_at`, and a free-text `notes` field unless stated otherwise. Deleting is soft-confirmed in the UI; deleting a roll that has prints must warn and list them.

### Catalogue tables (reference data, used in dropdowns)

**Manufacturer** — `name` (unique), `country` (optional).

**FilmStock** — `manufacturer_id`, `name` (e.g. "FP4 Plus"), `box_iso` (int), `type` (enum: B&W negative, B&W reversal, B&W chromogenic C-41, colour negative, colour slide, other), `formats_available` (text, e.g. "135, 120, sheet"), `aliases` (text — e.g. Kodak T-Max 400 is now sold as Ektapan 400), `discontinued` (bool).
Display name = "Manufacturer Name ISO", e.g. "Ilford FP4 Plus 125".

**Chemical** — `manufacturer_id`, `name`, `kind` (enum: film developer, paper developer, stop bath, fixer, wetting agent, hypo clear / washing aid, toner, other), `common_dilutions` (text, e.g. "stock; 1+1; 1+3"), `form` (liquid / powder).
Dropdowns are always **filtered by kind** (the film-developer field only shows film developers, etc.; water is allowed as a stop bath).

**Paper** — `manufacturer_id`, `name`, `base` (RC / FB), `contrast_type` (variable contrast / graded), `grade` (only if graded), `surface` (glossy, pearl, satin, matt, other), `tone` (neutral, warm, cool).

### Camera

`make`, `model`, `nickname` (optional, e.g. "the black FM2"), `camera_type` (enum: SLR, rangefinder, TLR, medium-format SLR, viewfinder/compact, large format, other), `format` (135, 120 6×4.5, 120 6×6, 120 6×7, 120 6×9, 4×5, 5×7, 8×10, other), `lens_mount`, `lenses` (free text — lenses owned for this body), `serial_number`, `year_made`, `shutter` (text, e.g. "mechanical, 1s–1/4000, B"), `metering` (text, e.g. "TTL centre-weighted" or "none"), `battery` (text), `acquired_date`, `acquired_price` (optional), `status` (active / retired / sold / broken), `photo` (optional image path), `notes`.
Display name = nickname if set, otherwise "Make Model".

### Roll

| Field | Notes |
|---|---|
| `code` | Short unique identifier the user writes on the negative sleeve. Auto-suggest `YYYY-NNN` (next free number for the year) but allow any text. |
| `title` | Optional human name ("Moselle walk", "Grandma's 90th") |
| `film_stock_id` | Dropdown (searchable) with "+ New film stock…" entry that opens a small dialog |
| `format` | Defaults from the chosen camera's format |
| `exposures` | int, optional |
| `shot_iso` (EI) | Defaults to the film's box ISO |
| `push_pull_stops` | Float in ⅓-stop steps, e.g. +1, +2, −1, +0.33. **Auto-calculated** as log2(EI / box ISO) rounded to ⅓ when EI changes; user can override. Shown as a badge: "Push +1", "Pull −1", "Box speed". |
| `camera_id` | Dropdown of cameras (active ones first, retired ones greyed), nullable |
| `lens` | Free text, optional (autocomplete from the camera's `lenses` field) |
| `film_expiry` | Optional; flag expired film |
| `date_loaded`, `date_finished` | Optional dates |
| `subject_location` | Free text |
| `status` | `loaded` → `exposed` → `developed` (enum). Only the developed state allows a Development record (see below). |
| `tags` | Many-to-many with a simple `Tag` table (e.g. "street", "family", "test roll") |
| `contact_sheet_image` | Optional image (scan of contact sheet or negatives) |
| `notes` | |

### Development (one per roll, created when the roll is marked developed)

| Field | Notes |
|---|---|
| `roll_id` | unique FK |
| `date_developed` | defaults to today |
| `developer_id` | Chemical where kind = film developer |
| `dilution` | Text with quick-pick chips from the chemical's `common_dilutions` ("stock", "1+1", "1+3", "1+9", "1+14", "1+25", "1+31", "1+50") |
| `temperature_c` | Default 20.0 |
| `dev_time_s` | required |
| `agitation` | Text with presets the user can pick then edit: "Ilford: 4 inversions in first 10 s, then 4 inversions each minute"; "Kodak: 5–7 inversions in first 30 s, then 5 s every 30 s"; "Continuous rotary (Jobo)"; "Stand: 30 s initial, then none"; "Semi-stand: initial + one at half time"; "Custom". Presets stored in a small editable `AgitationPreset` table. |
| `presoak_s` | optional |
| `stop_chemical_id` | Chemical where kind = stop bath, or "Water" |
| `stop_time_s` | |
| `rinse_time_s` | (rinse between stop and fix, or water-stop rinse — label it simply "Rinse") |
| `fixer_id`, `fixer_dilution`, `fix_time_s` | |
| `wash_time_s`, `wash_method` | Method text, e.g. "Ilford method 5/10/20 inversions" or "running water" |
| `wetting_agent_id`, `wetting_time_s` | optional |
| `tank` | Free text, e.g. "Paterson Super System 4, 2-reel" |
| `developed_with_rolls` | Optional link to other rolls developed in the same tank (many-to-many) |
| `result_rating` | 1–5 (negatives quality: thin / good / dense etc.) |
| `notes` | |

### Print (many per roll)

| Field | Notes |
|---|---|
| `roll_id` | required |
| `frame` | Text (e.g. "12", "12A") |
| `title` | Optional |
| `date_printed` | Defaults to today |
| `paper_id`, `paper_size` | Size presets: 9×13 cm, 13×18 cm, 18×24 cm, 24×30 cm, 30×40 cm, 5×7", 8×10", 11×14", custom |
| `enlarger`, `enlarging_lens`, `aperture`, `head_height` | Optional free text / numbers (a later "Enlarger" catalogue is out of scope for v1) |
| `contrast_method` | Enum: **single filter**, **split grade**, **graded paper**, **no filter** |
| `exposures` | Child table `PrintExposure` (ordered): `filter_grade` (00, 0, ½, 1, 1½ … 5, or "none"), `seconds` (float, e.g. 12.5), `aperture` (optional), `purpose` (base / soft / hard / dodge / burn / flash), `note` (e.g. "burn sky +4 s grade 5"). Single-filter = one base row; split grade = soft + hard rows; dodge/burn rows optional. UI shows the total exposure time. |
| `developer_id`, `dev_dilution`, `dev_time_s`, `dev_temperature_c` | Chemical where kind = paper developer |
| `stop_chemical_id`, `stop_time_s` | |
| `fixer_id`, `fixer_dilution`, `fix_time_s` | |
| `wash_time_s` | |
| `toning` | Optional text (e.g. "Selenium 1+9, 3 min") |
| `is_final` | Bool — work print vs final print |
| `rating` | 1–5 |
| `image` | Optional scan/photo of the print |
| `notes` | |

Indexes: roll `code` unique; FKs indexed; search over roll code/title/notes/subject, film name, camera name.

---

## User interface

General:
- One main window. Left **sidebar** navigation: *Rolls*, *Prints*, *Cameras*, *Catalogue* (sub-tabs: Films, Chemicals, Papers, Agitation presets), *Statistics*.
- Follows the system light/dark theme by default; Settings offers Light / Dark / **Darkroom** (black background, dim red text, for use under the safelight).
- Everything is keyboard-friendly: `Ctrl+N` new item in the current view, `Ctrl+F` search, `Ctrl+S` save, `Esc` cancel, `Delete` delete with confirmation. Tab order follows the visual order of form fields.
- Lists are sortable, filterable tables with a live search box. Column choice/width remembered between sessions.
- Forms validate inline (red hint under the field), never with modal error popups for simple mistakes.
- Times are entered with a small time field that accepts `m:ss`; temperatures show the unit.

**Rolls view (the main screen)**
- Left: table of rolls — code, title, film, EI + push/pull badge, camera, status chip (loaded / exposed / developed), date developed, number of prints. Filters: status, film stock, camera, developer, year, tag.
- Right: detail pane with tabs **Roll**, **Development**, **Prints**, **Images**.
- A prominent **"Mark as developed"** button on undeveloped rolls. It opens the development form, **pre-filled from the most recent development using the same film stock at the same EI** (fallback: same film stock, then last development overall). Show a small note "Pre-filled from roll 2026-012 — edit as needed".
- Prints tab lists the roll's prints as cards (thumbnail if available, frame, paper, contrast summary such as "Split: 00 8 s + 5 6 s", rating) with "Add print" and "Duplicate print" (duplicating copies all settings, so the next attempt only needs tweaks).

**Prints view** — all prints across rolls, filterable by paper, developer, contrast method, final only, rating; double-click opens the print with a link back to its roll.

**Cameras view** — card or table layout with photo, name, format, mount, status, and "rolls shot" count; detail shows the camera's fields and a list of its rolls.

**Catalogue view** — editable lists of film stocks, chemicals, papers, manufacturers, agitation presets. Items in use cannot be deleted (offer "mark discontinued" instead).

**Statistics view** (simple, v1) — rolls per year, most used films/developers/cameras, push/pull distribution. Plain Qt charts (QtCharts) — keep it light.

**Recipe lookup** — in the Development form, a "Show past results" side panel listing previous developments for the same film stock + developer + dilution with EI, time, temperature, agitation and rating, so the user can see what worked before.

---

## Other features

- **Images**: drag-and-drop or file picker; copy the file into the app's `images/` folder (don't reference the original path); generate thumbnails; deleting a record deletes its images after confirmation.
- **Export**: File → Export to CSV (one file per entity, zipped) and JSON (full nested dump). File → Export a single roll as a printable PDF "darkroom card" (roll info + development + prints) via `QPrinter` / `QTextDocument`.
- **Backup**: File → Back up database now (saves to a chosen location); automatic backup before migrations (see above).
- **Import**: JSON import of a previous export (merge by roll code, ask on conflicts). CSV import is out of scope for v1.
- **Seed data**:
  - On first launch with an empty DB, insert the **catalogue seed data** below (manufacturers, film stocks, chemicals, papers, agitation presets).
  - Demo cameras/rolls/prints are **not** inserted automatically. Offer them via *Help → Load demo data*, mark them with an `is_demo` flag, and offer *Help → Remove demo data*.
  - Seed data lives in `filmlog/seed/*.json`, not hard-coded in Python.

---

## Seed data

Development times below are manufacturer/commonly published starting points at 20 °C. Store them in the demo records as realistic examples; in the UI never present them as authoritative.

### Film stocks (B&W unless noted)

| Manufacturer | Film | Box ISO | Notes |
|---|---|---|---|
| Ilford | Pan F Plus | 50 | |
| Ilford | FP4 Plus | 125 | |
| Ilford | HP5 Plus | 400 | Pushes well to 800/1600 |
| Ilford | Delta 100 Professional | 100 | |
| Ilford | Delta 400 Professional | 400 | |
| Ilford | Delta 3200 Professional | 3200 | Nominal ISO ~1000 |
| Ilford | SFX 200 | 200 | Extended red sensitivity |
| Ilford | Ortho Plus | 80 | Orthochromatic |
| Ilford | XP2 Super | 400 | Chromogenic, C-41 |
| Kentmere | Pan 100 / Pan 200 / Pan 400 | 100 / 200 / 400 | Three separate entries |
| Kodak | Tri-X 400 | 400 | |
| Kodak | Ektapan 100 | 100 | Alias: T-Max 100 |
| Kodak | Ektapan 400 | 400 | Alias: T-Max 400 |
| Kodak | Ektapan P3200 | 3200 | Alias: T-Max P3200; 135 only |
| Kodak | Double-X 5222 | 250 | Motion picture stock; also sold as CineStill BwXX |
| Fujifilm | Neopan 100 Acros II | 100 | |
| Foma | Fomapan 100 Classic / 200 Creative / 400 Action | 100 / 200 / 400 | Three entries |
| Foma | Retropan 320 Soft | 320 | |
| Rollei | RPX 25 / RPX 100 / RPX 400 | 25 / 100 / 400 | Three entries |
| Rollei | Infrared 400 | 400 | |
| Adox | CHS 100 II | 100 | |
| Adox | Scala 50 | 50 | B&W reversal |
| Bergger | Pancro 400 | 400 | |
| AgfaPhoto | APX 100 / APX 400 | 100 / 400 | |
| Lomography | Earl Grey 100 / Lady Grey 400 | 100 / 400 | |

### Chemicals

- **Film developers:** Ilford ID-11 (powder; stock, 1+1, 1+3), Ilford Ilfosol 3 (1+9, 1+14), Ilford DD-X (1+4), Ilford Perceptol (stock, 1+1, 1+3), Ilford Microphen (stock, 1+1, 1+3), Ilford Ilfotec LC29 (1+9, 1+19, 1+29), Ilford Ilfotec HC (1+15, 1+31), Kodak D-76 (powder; stock, 1+1, 1+3), Kodak HC-110 (dil. B 1+31, dil. H 1+63), Kodak XTOL (powder; stock, 1+1, 1+2), Adox Adonal / R09 One Shot (Rodinal type; 1+25, 1+50, 1+100), Adox FX-39 II (1+9, 1+14), Kodak T-Max Developer (1+4), CineStill Df96 (monobath; stock).
- **Paper developers:** Ilford Multigrade (1+9, 1+14), Ilford PQ Universal (1+9), Ilford Bromophen (powder; 1+3), Kodak Dektol (powder; 1+2), Moersch Eco 4812 (1+9).
- **Stop baths:** Ilford Ilfostop (1+19), Kodak Indicator Stop Bath, plus a built-in "Water" option.
- **Fixers:** Ilford Rapid Fixer (1+4 film & paper, 1+9 paper), Ilford Hypam (1+4), Adox Adofix Plus (1+5, 1+7), Kodak Professional Fixer.
- **Wetting agents:** Ilford Ilfotol (1+200), Kodak Photo-Flo 200 (1+200).
- **Washing aid:** Ilford Washaid (1+4).
- **Toner:** Kodak/Harman Selenium toner (1+9 to 1+20).

### Papers

Ilford Multigrade RC Deluxe (glossy, pearl, satin), Ilford Multigrade RC Cooltone (glossy, pearl), Ilford Multigrade FB Classic (glossy, matt), Ilford Multigrade FB Warmtone (glossy, semi-matt), Kentmere VC Select (RC glossy, lustre), Foma Fomaspeed Variant III (RC), Foma Fomabrom Variant 111 (FB), Adox MCC 110 (FB glossy), Adox MCP 312 (RC semi-matt), Bergger Prestige Variable CB (FB).

### Demo cameras

| Make | Model | Type | Format | Mount | Shutter / metering |
|---|---|---|---|---|---|
| Nikon | FM2 | SLR | 135 | Nikon F | Mechanical, 1 s–1/4000 s, B; TTL centre-weighted |
| Pentax | K1000 | SLR | 135 | Pentax K | Mechanical, 1 s–1/1000 s, B; TTL needle meter |
| Leica | M6 | Rangefinder | 135 | Leica M | Mechanical, 1 s–1/1000 s, B; TTL spot-ish |
| Olympus | OM-1 | SLR | 135 | Olympus OM | Mechanical, 1 s–1/1000 s, B; TTL (mercury battery) |
| Mamiya | RB67 Pro S | Medium-format SLR | 120 6×7 | Mamiya RB | Leaf shutter in lens, 1 s–1/400 s; no meter |
| Hasselblad | 500C/M | Medium-format SLR | 120 6×6 | Hasselblad V | Leaf shutter in lens, 1 s–1/500 s; no meter |
| Rolleiflex | 2.8F | TLR | 120 6×6 | Fixed Planar 80 mm f/2.8 | Synchro-Compur 1 s–1/500 s; coupled selenium meter |

### Demo rolls (with development)

1. `2026-001` — Ilford FP4 Plus @ EI 125 (box), Nikon FM2. Ilford ID-11 **stock, 8:30**, 20 °C, Ilford agitation; Ilfostop 1+19 10 s; Ilford Rapid Fixer 1+4 4:00; Ilfotol.
2. `2026-002` — Ilford FP4 Plus @ EI 125, Mamiya RB67. Ilford ID-11 **1+1, 11:00**, 20 °C.
3. `2026-003` — Ilford HP5 Plus @ EI 400, Leica M6. Ilford ID-11 **stock, 7:30**, 20 °C.
4. `2026-004` — Ilford HP5 Plus @ EI 400, Rolleiflex 2.8F. Ilford ID-11 **1+1, 13:00**, 20 °C.
5. `2026-005` — Kodak Tri-X 400 @ EI 400, Pentax K1000. Kodak D-76 **stock, 6:45**, 20 °C, Kodak agitation.
6. `2026-006` — Kodak Tri-X 400 @ EI 400, Nikon FM2. Kodak D-76 **1+1, 9:45**, 20 °C, Kodak agitation; water stop 30 s; rinse 30 s.
7. `2026-007` — Ilford HP5 Plus @ EI 1600 (**push +2**), Leica M6. Ilford Microphen stock (user to fill time — leave as an example with a note "check Ilford push chart").
8. `2026-008` — Fomapan 100 @ EI 100, Olympus OM-1 — status *exposed*, not yet developed (to demonstrate the "Mark as developed" flow).
9. `2026-009` — Kodak Ektapan 400 @ EI 400, Hasselblad 500C/M — status *loaded* (still in camera).

### Demo prints

- From `2026-001` frame 14: Ilford Multigrade RC Deluxe glossy, 18×24 cm. Single filter grade 2½, 14 s at f/8. Ilford Multigrade 1+9 **1:00**; Ilfostop 1+19 **0:10**; Rapid Fixer 1+4 **0:30**; wash 2:00. Work print, rating 3.
- Same frame, second attempt: **split grade** — grade 00 9 s + grade 5 7 s, plus burn sky grade 5 +4 s. Same chemistry. Final print, rating 5.
- From `2026-004` frame 7: Ilford Multigrade FB Classic glossy, 24×30 cm. Split grade 00 12 s + 5 10 s. Ilford Multigrade 1+9 **2:00**; Ilfostop 0:10; Rapid Fixer 1+4 1:00; Washaid; wash 30 min. Selenium toned 1+19, 4 min.
- From `2026-006` frame 22: Foma Fomaspeed Variant III RC, 13×18 cm, single filter grade 3, 10 s. Ilford Multigrade 1+14 **1:30**.

---

## Project structure

```
filmlog/
├── pyproject.toml
├── README.md               # install, run, data location, backup/restore
├── CLAUDE.md               # this file
├── alembic.ini
├── packaging/
│   ├── filmlog.desktop
│   ├── icons/              # SVG app icon + PNG sizes (hicolor)
│   ├── arch/PKGBUILD       # builds from local source / git tag
│   └── flatpak/            # (phase 6) manifest
├── src/filmlog/
│   ├── __main__.py         # `python -m filmlog`
│   ├── app.py              # QApplication setup, theme, main window
│   ├── paths.py            # platformdirs wrappers
│   ├── db/                 # engine/session, models.py, migrations/
│   ├── services/           # business logic (no Qt imports here!)
│   ├── ui/                 # views, dialogs, widgets, table models
│   ├── seed/               # catalogue.json, demo.json, loader.py
│   └── resources/          # icons, qss themes
└── tests/
```

Architecture rules:
- **Services layer has no Qt imports** and is fully unit-tested (push/pull calculation, time parsing/formatting, roll-code suggestion, pre-fill lookup, export/import, seed loading).
- UI talks to services, never directly builds SQL.
- Use Qt Model/View (`QAbstractTableModel` + `QSortFilterProxyModel`) for lists, not `QTableWidget`.
- Type hints everywhere; small, focused modules.

---

## How to work (instructions for Claude Code)

Build in phases. **After each phase: run `ruff`, `mypy` and `pytest`, make sure the app starts, summarise what was done, and make a git commit** with a clear message. Then continue to the next phase unless something needs my decision.

1. **Skeleton** — `git init`, pyproject (uv), package layout, empty main window with sidebar, theme switching, paths, README with run instructions.
2. **Data layer** — SQLAlchemy models, first Alembic migration, pre-migration backup, seed loader + catalogue seed JSON, unit tests for services.
3. **Cameras + Catalogue UI** — full CRUD for cameras, film stocks, chemicals, papers, presets.
4. **Rolls + Development UI** — roll list/detail, push/pull auto-calc, status flow, "Mark as developed" with pre-fill and past-results panel.
5. **Prints UI** — print form with the exposure table (single / split grade / dodge / burn), duplicate print, prints view, images & thumbnails.
6. **Extras & packaging** — statistics, export/import/backup, PDF darkroom card, demo data load/remove, `.desktop` file and icon, Arch `PKGBUILD`, short notes in README on Flatpak/AppImage for other distros.

Guidelines:
- If a requirement here is ambiguous, pick the simplest sensible option, note the decision in `docs/decisions.md`, and keep going; only stop to ask me for things that would be hard to undo (e.g. changing the data model after real data exists).
- Never delete or overwrite `~/.local/share/filmlog/filmlog.db` during development; use a separate DB via env var `FILMLOG_DB=/tmp/filmlog-dev.db` for testing and demo runs.
- Keep dependencies minimal: PySide6, SQLAlchemy, Alembic, platformdirs (+ dev deps). Ask before adding others.
- On Arch, system packages exist for the runtime deps (`pyside6`, `python-sqlalchemy`, `python-alembic`, `python-platformdirs`); the PKGBUILD should depend on those rather than vendoring.
- English UI text, all strings wrapped for translation (`self.tr(...)`) so a German/French translation can be added later.
- Metric by default (°C, cm), with °F and inches available in Settings.
