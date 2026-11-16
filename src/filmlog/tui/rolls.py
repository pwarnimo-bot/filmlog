# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rolls tab, the roll screen (tabs Roll / Development / Prints / Images) and their dialogs."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from filmlog.db.enums import ChemicalKind, FilmFormat, RollStatus
from filmlog.db.models import Development, FilmStock, Print, Roll
from filmlog.services import catalogue, lookup, records
from filmlog.services import development as dev_service
from filmlog.services import rolls as roll_service
from filmlog.services.images import image_path, images_of_roll
from filmlog.services.pushpull import badge_kind, badge_text, compute_stops
from filmlog.services.timefmt import format_duration
from filmlog.tui import prints as print_ui
from filmlog.tui.catalogue import save_new_film
from filmlog.tui.forms import NEW, RATING_OPTIONS, ConfirmScreen, Field, FormScreen, PromptScreen
from filmlog.tui.listpane import Col, ListPane, chip, select_value
from filmlog.tui.options import (
    camera_options,
    chem_options,
    dilution_suggestions,
    enum_options,
    film_options,
    label,
)
from filmlog.tui.records import apply_values, check_image_path, take_image

if TYPE_CHECKING:
    from filmlog.tui.app import FilmLogTUI

PREFILL_REASONS = {
    "same_film_ei": "same film and EI",
    "same_film": "same film",
    "last": "your last development",
}


def stars(n: int | None) -> str:
    return "★" * n + "☆" * (5 - n) if n else ""


def ei_cell(app: Any, r: Roll) -> Text:
    t = Text(f"{r.shot_iso} ")
    t.append_text(chip(app, badge_text(r.push_pull_stops), badge_kind(r.push_pull_stops)))
    return t


# --------------------------------------------------------------------------- roll form

_ROLL_KEYS = (
    "code",
    "title",
    "film_stock_id",
    "camera_id",
    "lens",
    "format",
    "exposures",
    "shot_iso",
    "push_pull_stops",
    "status",
    "subject_location",
    "date_loaded",
    "date_finished",
    "film_expiry",
    "notes",
)


def edit_roll(app: FilmLogTUI, roll: Roll, on_saved: Any = None) -> None:
    s = app.session
    is_new = roll.id is None
    cam = roll.camera
    fields = [
        Field("code", "Code", required=True, placeholder="written on the negative sleeve"),
        Field("title", "Title", placeholder="optional, e.g. Moselle walk"),
        Field(
            "film_stock_id",
            "Film",
            "select",
            film_options(s, roll.film_stock_id),
            required=True,
            placeholder="type to search; last entry adds a new film",
        ),
        Field("camera_id", "Camera", "select", camera_options(s)),
        Field("lens", "Lens", suggestions=cam.lens_list if cam else []),
        Field("format", "Format", "select", enum_options(FilmFormat), allow_blank=False),
        Field("exposures", "Exposures", "int"),
        Field("shot_iso", "EI (shot at)", "int", required=True),
        Field(
            "push_pull_stops",
            "Push / pull",
            "stops",
            placeholder="calculated from EI; override in ⅓ stops",
        ),
        Field("status", "Status", "select", enum_options(RollStatus), allow_blank=False),
        Field("subject_location", "Subject / location"),
        Field(
            "tags",
            "Tags",
            placeholder="comma-separated, e.g. street, family",
            suggestions=[t.name for t in roll_service.all_tags(s)],
        ),
        Field("dates", "Dates", "section"),
        Field("date_loaded", "Loaded", "date"),
        Field("date_finished", "Finished", "date"),
        Field("film_expiry", "Film expiry", "date"),
        Field("more", "More", "section"),
        Field(
            "image_path",
            "Contact sheet",
            placeholder=(
                f"current: {roll.contact_sheet_image} — " if roll.contact_sheet_image else ""
            )
            + "path to a scan of the contact sheet / negatives",
        ),
        Field("notes", "Notes", "area"),
    ]
    values = {k: getattr(roll, k) for k in _ROLL_KEYS}
    values["tags"] = ", ".join(t.name for t in roll.tags)
    values["image_path"] = ""
    state = {"box": roll.film_stock.box_iso if roll.film_stock_id else None}

    def film_changed(form: FormScreen, film: FilmStock) -> None:
        ei = form.value("shot_iso")
        if ei is None or ei == state["box"]:
            form.set_raw("shot_iso", film.box_iso)
            ei = film.box_iso
        state["box"] = film.box_iso
        form.set_raw("push_pull_stops", compute_stops(ei, film.box_iso))

    def on_change(form: FormScreen, key: str) -> None:
        if key == "film_stock_id":
            fid = form.raw("film_stock_id")
            if fid == NEW:

                def created(film: FilmStock) -> None:
                    form.set_options("film_stock_id", film_options(s, film.id), film.id)
                    film_changed(form, film)

                form.set_raw("film_stock_id", None)
                save_new_film(app, created)
            elif fid is not None:
                film_changed(form, s.get(FilmStock, fid))  # type: ignore[arg-type]
        elif key == "shot_iso":
            ei = form.value("shot_iso")
            if ei and state["box"]:
                form.set_raw("push_pull_stops", compute_stops(ei, state["box"]))
        elif key == "camera_id":
            from textual.suggester import SuggestFromList
            from textual.widgets import Input

            from filmlog.db.models import Camera

            c = s.get(Camera, form.raw("camera_id")) if form.raw("camera_id") else None
            if c is not None:
                form.set_raw("format", c.format)
                if len(c.lens_list) == 1:
                    form.set_raw("lens", c.lens_list[0])
                w = form.widget("lens")
                if isinstance(w, Input):
                    w.suggester = SuggestFromList(c.lens_list, case_sensitive=False)

    def validate(v: dict[str, Any]) -> dict[str, str]:
        e: dict[str, str] = {}
        if roll_service.code_exists(s, v["code"], exclude_id=roll.id):
            e["code"] = "Another roll already uses this code."
        if v["film_stock_id"] in (None, NEW):
            e["film_stock_id"] = "Choose the film stock."
        if roll.development is not None and v["status"] != RollStatus.DEVELOPED:
            e["status"] = (
                "This roll has a development record; remove it on the Development tab first."
            )
        if v["shot_iso"] is not None and v["shot_iso"] <= 0:
            e["shot_iso"] = "EI must be positive."
        img = check_image_path(v.get("image_path") or "")
        if img:
            e["image_path"] = img
        return e

    def done(result: dict[str, Any] | None) -> None:
        if result is None:
            return
        tags = roll_service.parse_tags(result.pop("tags"))
        image = result.pop("image_path")
        with s.no_autoflush:
            apply_values(s, roll, result)
            roll.tags = roll_service.get_or_create_tags(s, tags)
            if image:
                roll.contact_sheet_image = take_image(image)
        s.add(roll)
        roll_service.prune_unused_tags(s)
        s.commit()
        app.data_changed(select=roll)
        app.notify(f"Saved roll {roll.code}.")
        if on_saved is not None:
            on_saved(roll)

    app.push_screen(
        FormScreen(
            "New roll" if is_new else f"Roll {roll.code}",
            fields,
            values,
            validate=validate,
            on_change=on_change,
        ),
        done,
    )


def new_roll(app: FilmLogTUI, on_saved: Any = None) -> None:
    roll = Roll(
        code=roll_service.suggest_code(app.session),
        status=RollStatus.LOADED,
        format=FilmFormat.F135,
        push_pull_stops=0.0,
        title="",
        lens="",
        subject_location="",
        notes="",
    )
    edit_roll(app, roll, on_saved)


# --------------------------------------------------------------------------- development form

_DEV_KEYS = (
    "date_developed",
    "developer_id",
    "dilution",
    "temperature_c",
    "dev_time_s",
    "agitation",
    "presoak_s",
    "stop_chemical_id",
    "stop_time_s",
    "rinse_time_s",
    "fixer_id",
    "fixer_dilution",
    "fix_time_s",
    "wash_time_s",
    "wash_method",
    "wetting_agent_id",
    "wetting_time_s",
    "tank",
    "result_rating",
    "notes",
)


def edit_development(
    app: FilmLogTUI, roll: Roll, dev: Development, *, note: str = "", on_saved: Any = None
) -> None:
    s = app.session
    is_new = roll.development is not dev
    presets = catalogue.agitation_presets(s)
    fields = [
        Field("date_developed", "Date developed", "date"),
        Field(
            "developer_id",
            "Developer",
            "select",
            chem_options(s, [ChemicalKind.FILM_DEVELOPER], dev.developer_id),
        ),
        Field(
            "dilution",
            "Dilution",
            suggestions=dilution_suggestions(s, dev.developer_id),
            placeholder="e.g. stock, 1+1 (→ completes)",
        ),
        Field("dev_time_s", "Dev time", "time", required=True),
        Field("temperature_c", "Temperature", "temp", required=True),
        Field(
            "preset",
            "Agitation preset",
            "select",
            [(p.name, p.id) for p in presets],
            placeholder="picking one fills the text below, which you can edit",
        ),
        Field("agitation", "Agitation", "area"),
        Field("presoak_s", "Presoak", "time"),
        Field("stopfix", "Stop & fix", "section"),
        Field(
            "stop_chemical_id",
            "Stop bath",
            "select",
            chem_options(s, [ChemicalKind.STOP_BATH], dev.stop_chemical_id),
        ),
        Field("stop_time_s", "Stop time", "time"),
        Field("rinse_time_s", "Rinse", "time"),
        Field("fixer_id", "Fixer", "select", chem_options(s, [ChemicalKind.FIXER], dev.fixer_id)),
        Field(
            "fixer_dilution", "Fixer dilution", suggestions=dilution_suggestions(s, dev.fixer_id)
        ),
        Field("fix_time_s", "Fix time", "time"),
        Field("wash", "Wash & dry", "section"),
        Field("wash_time_s", "Wash time", "time"),
        Field("wash_method", "Wash method", placeholder="e.g. Ilford method 5/10/20 inversions"),
        Field(
            "wetting_agent_id",
            "Wetting agent",
            "select",
            chem_options(s, [ChemicalKind.WETTING_AGENT], dev.wetting_agent_id),
        ),
        Field("wetting_time_s", "Wetting time", "time"),
        Field("tank", "Tank", placeholder="e.g. Paterson Super System 4, 2-reel"),
        Field(
            "with", "Developed with", placeholder="codes of rolls in the same tank, comma-separated"
        ),
        Field(
            "result_rating",
            "Negatives",
            "select",
            RATING_OPTIONS,
            placeholder="1 = poor … 5 = excellent",
        ),
        Field("notes", "Notes", "area"),
    ]
    values = {k: getattr(dev, k) for k in _DEV_KEYS}
    values["with"] = ", ".join(r.code for r in dev.developed_with_rolls)

    def on_change(form: FormScreen, key: str) -> None:
        from textual.suggester import SuggestFromList
        from textual.widgets import Input

        if key == "preset":
            pid = form.raw("preset")
            preset = next((p for p in presets if p.id == pid), None)
            if preset is not None:
                form.set_raw("agitation", preset.text)
        elif key in ("developer_id", "fixer_id"):
            target = "dilution" if key == "developer_id" else "fixer_dilution"
            w = form.widget(target)
            if isinstance(w, Input):
                w.suggester = SuggestFromList(dilution_suggestions(s, form.raw(key)))

    def past(form: FormScreen) -> None:
        def use(d: Development | None) -> None:
            if d is None:
                return
            form.set_raw("dilution", d.dilution)
            form.set_raw("dev_time_s", d.dev_time_s)
            form.set_raw("temperature_c", d.temperature_c)
            form.set_raw("agitation", d.agitation)
            if d.developer_id:
                form.set_raw("developer_id", d.developer_id)
            form.set_note(
                f"Copied dilution, time, temperature and agitation from roll "
                f"{d.roll.code} — edit as needed."
            )

        app.push_screen(
            PastResultsScreen(roll, form.raw("developer_id"), form.value("dilution") or ""), use
        )

    def validate(v: dict[str, Any]) -> dict[str, str]:
        e: dict[str, str] = {}
        if v.get("dev_time_s") == 0:
            e["dev_time_s"] = "Enter the development time."
        for code in roll_service.parse_tags(v.get("with") or ""):
            try:
                lookup.find_roll(s, code)
            except LookupError:
                e["with"] = f"No roll with code {code}."
        return e

    def done(result: dict[str, Any] | None) -> None:
        if result is None:
            return
        result.pop("preset")
        codes = roll_service.parse_tags(result.pop("with"))
        with s.no_autoflush:
            apply_values(s, dev, result)
            dev.developed_with_rolls = [
                x for c in codes if (x := lookup.find_roll(s, c)) is not roll
            ]
            if is_new:
                dev_service.mark_developed(roll, dev)
        s.commit()
        app.data_changed(select=roll)
        app.notify(f"Development of roll {roll.code} saved.")
        if on_saved is not None:
            on_saved(roll)

    title = f"Develop roll {roll.code}" if is_new else f"Development — roll {roll.code}"
    app.push_screen(
        FormScreen(
            title,
            fields,
            values,
            note=note,
            validate=validate,
            on_change=on_change,
            temp_unit=app.settings.temperature_unit,
            buttons=[("Past results…", "past", past)],
        ),
        done,
    )


def mark_developed(app: FilmLogTUI, roll: Roll, on_saved: Any = None) -> None:
    dev, pre = dev_service.new_development_for(app.session, roll)
    note = ""
    if pre is not None:
        note = (
            f"Pre-filled from roll {pre.source.roll.code} "
            f"({PREFILL_REASONS.get(pre.reason, pre.reason)}) — edit as needed. "
            "Published times are starting points, not gospel."
        )
    edit_development(app, roll, dev, note=note, on_saved=on_saved)


class PastResultsScreen(ModalScreen[Development | None]):
    """Previous developments of the same film + developer (+ dilution)."""

    BINDINGS = [Binding("escape", "close", "Close")]
    DEFAULT_CSS = """
    PastResultsScreen { align: center middle; }
    PastResultsScreen #box {
        width: 120; max-width: 100%; height: 80%; border: thick $primary;
        background: $surface; padding: 0 1;
    }
    PastResultsScreen #caption { color: $text-muted; padding: 0 0 1 0; }
    PastResultsScreen DataTable { height: 1fr; }
    PastResultsScreen #buttons { height: auto; padding: 1 0 0 0; align-horizontal: right; }
    PastResultsScreen Button { margin: 0 0 0 1; }
    """

    def __init__(self, roll: Roll, developer_id: int | None, dilution: str) -> None:
        super().__init__()
        self.roll = roll
        self.developer_id = developer_id
        self.dilution = dilution
        self.devs: list[Development] = []

    def compose(self) -> ComposeResult:
        from filmlog.db.models import Chemical

        tui: FilmLogTUI = self.app  # type: ignore[assignment]
        dev = tui.session.get(Chemical, self.developer_id) if self.developer_id else None
        what = self.roll.film_stock.display_name + (f" in {dev.display_name}" if dev else "")
        with Vertical(id="box"):
            yield Static(f"Past results — {what}", classes="title")
            yield Static(
                "What worked before. Enter (or Use) copies dilution, time, "
                "temperature and agitation into the form.",
                id="caption",
            )
            yield Checkbox(
                f"Same dilution only ({self.dilution or 'any'})",
                bool(self.dilution),
                id="same",
                compact=True,
            )
            yield DataTable(cursor_type="row", zebra_stripes=True)
            with Horizontal(id="buttons"):
                yield Button("Close", id="close")
                yield Button("Use selected", id="use", variant="primary")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(
            "Roll", "Date", "EI", "Developer", "Time", "Temp", "Agitation", "Result"
        )
        self._fill()
        self.query_one(DataTable).focus()

    def _fill(self) -> None:
        tui: FilmLogTUI = self.app  # type: ignore[assignment]
        same = self.query_one("#same", Checkbox).value
        self.devs = list(
            dev_service.past_results(
                tui.session,
                self.roll.film_stock_id,
                self.developer_id,
                self.dilution if same else None,
                exclude_roll_id=self.roll.id,
            )
        )
        table = self.query_one(DataTable)
        table.clear()
        unit = tui.settings.temperature_unit
        from filmlog.services.units import format_temp

        for d in self.devs:
            table.add_row(
                d.roll.code,
                str(d.date_developed or ""),
                f"{d.roll.shot_iso} {badge_text(d.roll.push_pull_stops)}",
                (d.developer.display_name if d.developer else "") + f" {d.dilution}",
                format_duration(d.dev_time_s),
                format_temp(d.temperature_c, unit),
                d.agitation,
                stars(d.result_rating),
            )
        table.border_subtitle = f"{len(self.devs)} found" if self.devs else "No matches yet"

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._fill()

    def _use(self) -> None:
        table = self.query_one(DataTable)
        if self.devs and table.cursor_row is not None and table.cursor_row < len(self.devs):
            self.dismiss(self.devs[table.cursor_row])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self._use()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "use":
            self._use()
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------- roll screen


def _kv(rows: Sequence[tuple[str, Any]]) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim", justify="right", no_wrap=True)
    t.add_column()
    for k, v in rows:
        if v not in (None, "", []):
            t.add_row(k, v if isinstance(v, Text) else str(v))
    return t


def _chem(c: Any, dilution: str = "", seconds: int | None = None) -> str:
    text = (c.display_name + (f" {dilution}" if dilution else "")) if c is not None else ""
    t = format_duration(seconds)
    return f"{text}, {t}" if text and t else text or t


class RollPrintsPane(ListPane):
    new_label = "Add print"
    show_search = False
    empty_text = "No prints from this roll yet"
    extra_buttons = [("Duplicate", "dup")]

    def __init__(self, roll: Roll) -> None:
        super().__init__()
        self.roll = roll

    def on_mount(self) -> None:
        self.columns = print_ui.print_columns(self.app, with_roll=False)
        super().on_mount()

    def fetch(self) -> Sequence[Any]:
        return list(self.roll.prints)

    def _saved(self, p: Print) -> None:
        self.reload(select=p)
        screen = self.screen
        if isinstance(screen, RollScreen):
            screen.refresh_view()

    def new_item(self) -> None:
        print_ui.new_print(self.tui, self.roll, on_saved=self._saved)

    def open_item(self, obj: Any) -> None:
        print_ui.edit(self.tui, obj, on_saved=self._saved)

    def extra_action(self, cls: str) -> None:
        obj = self.current()
        if obj is None:
            self.app.notify("Select a print to duplicate.", severity="warning")
            return
        print_ui.duplicate(self.tui, obj, on_saved=self._saved)

    def delete_item(self, obj: Any) -> None:
        def after() -> None:
            self.reload()
            screen = self.screen
            if isinstance(screen, RollScreen):
                screen.refresh_view()

        print_ui.confirm_delete(self.tui, obj, after)


class RollScreen(Screen[None]):
    """Everything about one roll, in tabs."""

    BINDINGS = [
        Binding("escape", "back", "Back to list"),
        Binding("e", "edit", "Edit roll"),
        Binding("m", "develop", "Mark as developed / edit development"),
        Binding("p", "add_print", "Add print"),
        Binding("c", "card", "Darkroom card"),
    ]
    DEFAULT_CSS = """
    RollScreen #head { height: auto; padding: 0 1; }
    RollScreen #heading { text-style: bold; color: $primary; width: 1fr; }
    RollScreen #badges { width: auto; }
    RollScreen #actions { height: auto; padding: 0 1 1 1; }
    RollScreen #actions Button { margin: 0 1 0 0; }
    RollScreen TabbedContent { height: 1fr; }
    RollScreen .info { padding: 1 1; height: auto; }
    RollScreen .tabbar { height: auto; padding: 0 1; }
    RollScreen .tabbar Button { margin: 0 1 0 0; }
    """

    def __init__(self, roll: Roll) -> None:
        super().__init__()
        self.roll = roll

    @property
    def tui(self) -> FilmLogTUI:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with Horizontal(id="head"):
            yield Static("", id="heading")
            yield Static("", id="badges")
        with Horizontal(id="actions"):
            yield Button("Edit roll", id="edit", compact=True)
            yield Button("Mark as developed", id="develop", variant="primary", compact=True)
            yield Button("Add print", id="add-print", compact=True)
            yield Button("Darkroom card…", id="card", compact=True)
            yield Button("Delete roll", id="delete", variant="error", compact=True)
            yield Button("Back", id="close", compact=True)
        with TabbedContent(id="roll-tabs"):
            with TabPane("Roll", id="t-roll"), VerticalScroll():
                yield Static("", id="roll-info", classes="info")
            with TabPane("Development", id="t-dev"), VerticalScroll():
                with Horizontal(classes="tabbar"):
                    yield Button("Edit development", id="dev-edit", compact=True)
                    yield Button("Past results…", id="dev-past", compact=True)
                    yield Button(
                        "Remove development", id="dev-remove", variant="error", compact=True
                    )
                yield Static("", id="dev-info", classes="info")
            with TabPane("Prints", id="t-prints"):
                yield RollPrintsPane(self.roll)
            with TabPane("Images", id="t-images"), VerticalScroll():
                yield Static("", id="images-info", classes="info")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        r = self.roll
        app = self.app
        self.query_one("#heading", Static).update(
            f"Roll {r.code}" + (f" — {r.title}" if r.title else "")
        )
        badges = Text()
        badges.append_text(
            chip(
                app,
                f"EI {r.shot_iso} · {badge_text(r.push_pull_stops)}",
                badge_kind(r.push_pull_stops),
            )
        )
        badges.append(" ")
        badges.append_text(chip(app, label(r.status), r.status.value))
        self.query_one("#badges", Static).update(badges)
        has_dev = r.development is not None
        dev_btn = self.query_one("#develop", Button)
        dev_btn.display = not has_dev
        self.query_one("#dev-edit", Button).label = (
            "Edit development" if has_dev else ("Mark as developed…")
        )
        self.query_one("#dev-remove", Button).display = has_dev
        self.query_one("#dev-past", Button).display = has_dev

        expired = Text(" expired", style="bold red") if r.is_expired_film else ""
        expiry = Text(str(r.film_expiry or "")) + expired if r.film_expiry else None
        self.query_one("#roll-info", Static).update(
            _kv(
                [
                    ("Code", r.code),
                    ("Title", r.title),
                    ("Film", r.film_stock.display_name),
                    ("EI", ei_cell(app, r)),
                    ("Camera", r.camera.display_name if r.camera else ""),
                    ("Lens", r.lens),
                    ("Format", label(r.format)),
                    ("Exposures", r.exposures),
                    ("Status", label(r.status)),
                    ("Subject / location", r.subject_location),
                    ("Tags", ", ".join(t.name for t in r.tags)),
                    ("Loaded", r.date_loaded),
                    ("Finished", r.date_finished),
                    ("Film expiry", expiry),
                    ("Notes", r.notes),
                ]
            )
        )

        d = r.development
        if d is None:
            text: Any = Text(
                "Not developed yet.\n\nPress m (or “Mark as developed”) — the form is pre-filled "
                "from your most recent development of the same film at the same EI.",
                style="dim",
            )
        else:
            unit = self.tui.settings.temperature_unit
            from filmlog.services.units import format_temp

            text = _kv(
                [
                    ("Date", d.date_developed),
                    ("Developer", _chem(d.developer, d.dilution)),
                    (
                        "Time",
                        f"{format_duration(d.dev_time_s)} at {format_temp(d.temperature_c, unit)}",
                    ),
                    ("Agitation", d.agitation),
                    ("Presoak", format_duration(d.presoak_s)),
                    ("Stop", _chem(d.stop_chemical, "", d.stop_time_s)),
                    ("Rinse", format_duration(d.rinse_time_s)),
                    ("Fixer", _chem(d.fixer, d.fixer_dilution, d.fix_time_s)),
                    (
                        "Wash",
                        ", ".join(x for x in (format_duration(d.wash_time_s), d.wash_method) if x),
                    ),
                    ("Wetting agent", _chem(d.wetting_agent, "", d.wetting_time_s)),
                    ("Tank", d.tank),
                    ("Developed with", ", ".join(x.code for x in d.developed_with_rolls)),
                    ("Negatives", stars(d.result_rating)),
                    ("Notes", d.notes),
                ]
            )
        self.query_one("#dev-info", Static).update(text)

        lines = Text()
        names = images_of_roll(r)
        if not names:
            lines.append(
                "No images yet. Attach a contact sheet with “Edit roll”, and print "
                "scans in each print's form.",
                style="dim",
            )
        else:
            lines.append("Image files (most terminals open them with ctrl+click):\n\n")
            for n in names:
                lines.append(f"  {image_path(n)}\n")
        self.query_one("#images-info", Static).update(lines)
        tabs = self.query_one("#roll-tabs", TabbedContent)
        tabs.get_tab("t-prints").label = f"Prints ({len(r.prints)})"  # type: ignore[assignment]

    # -- actions ----------------------------------------------------------------

    def _after(self, *_: Any) -> None:
        self.refresh_view()
        self.query_one(RollPrintsPane).reload()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_edit(self) -> None:
        edit_roll(self.tui, self.roll, on_saved=self._after)

    def action_develop(self) -> None:
        r = self.roll
        if r.development is not None:
            edit_development(self.tui, r, r.development, on_saved=self._after)
        else:
            mark_developed(self.tui, r, on_saved=self._after)

    def action_add_print(self) -> None:
        self.query_one("#roll-tabs", TabbedContent).active = "t-prints"
        self.query_one(RollPrintsPane).new_item()

    def action_card(self) -> None:
        default = str(Path.home() / f"darkroom-card-{self.roll.code}.pdf")

        def write(path: str | None) -> None:
            if not path:
                return
            from filmlog.cli.rolls import write_pdf_file
            from filmlog.services.card import roll_card_html

            out = Path(path).expanduser()
            s = self.tui.settings
            html = roll_card_html(self.roll, s.temperature_unit, s.length_unit)
            try:
                if out.suffix.lower() in (".html", ".htm"):
                    out.write_text(html, encoding="utf-8")
                else:
                    write_pdf_file(html, out)
            except Exception as exc:  # noqa: BLE001 - show any failure to the user
                self.app.notify(f"Could not write the card: {exc}", severity="error")
                return
            self.app.notify(f"Darkroom card saved to {out}")

        self.app.push_screen(
            PromptScreen("Save the darkroom card as (.pdf or .html):", default, ok="Save"), write
        )

    def action_delete(self) -> None:
        def answer(ok: bool | None) -> None:
            if ok:
                records.delete_roll(self.tui.session, self.roll)
                self.app.pop_screen()
                self.tui.data_changed()
                self.app.notify("Roll deleted.")

        self.app.push_screen(
            ConfirmScreen(records.roll_delete_question(self.roll), yes="Delete"), answer
        )

    def _remove_development(self) -> None:
        def answer(ok: bool | None) -> None:
            if ok:
                records.remove_development(self.tui.session, self.roll)
                self.tui.data_changed(select=self.roll)
                self._after()

        self.app.push_screen(
            ConfirmScreen(
                f"Remove the development record of roll {self.roll.code}? "
                "The roll goes back to “exposed”.",
                yes="Remove",
            ),
            answer,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        handlers = {
            "edit": self.action_edit,
            "develop": self.action_develop,
            "dev-edit": self.action_develop,
            "add-print": self.action_add_print,
            "card": self.action_card,
            "delete": self.action_delete,
            "close": self.action_back,
            "dev-remove": self._remove_development,
            "dev-past": self._show_past,
        }
        handler = handlers.get(event.button.id or "")
        if handler is not None:
            event.stop()
            handler()

    def _show_past(self) -> None:
        d = self.roll.development
        self.app.push_screen(
            PastResultsScreen(self.roll, d.developer_id if d else None, d.dilution if d else "")
        )


# --------------------------------------------------------------------------- rolls tab


class RollsPane(ListPane):
    new_label = "New roll"
    empty_text = "No rolls yet — ctrl+n adds one (or load demo data from the command palette)"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        app = self
        self.columns = [
            Col("Code", lambda r: r.code, width=10),
            Col(
                "Status",
                lambda r: r.status.value,
                sort=lambda r: list(RollStatus).index(r.status),
                render=lambda r: chip(app.app, label(r.status), r.status.value),
                width=11,
            ),
            Col("Title", lambda r: r.title, width=16),
            Col("Film", lambda r: r.film_stock.display_name, width=22),
            Col(
                "EI",
                lambda r: f"{r.shot_iso} {badge_text(r.push_pull_stops)}",
                sort=lambda r: r.shot_iso,
                render=lambda r: ei_cell(app.app, r),
                width=15,
            ),
            Col("Camera", lambda r: r.camera.display_name if r.camera else "", width=14),
            Col(
                "Developed",
                lambda r: r.development.date_developed if r.development else "",
                sort=lambda r: (
                    r.development.date_developed
                    if r.development and r.development.date_developed
                    else dt.date.min
                ),
                width=10,
            ),
            Col(
                "Prints",
                lambda r: len(r.prints) or "",
                sort=lambda r: len(r.prints),
                right=True,
                width=6,
            ),
        ]

    def filter_widgets(self) -> list[Select[Any]]:
        return [
            Select(enum_options(RollStatus), prompt="Any status", id="f-status", compact=True),
            Select([], prompt="Any film", id="f-film", compact=True),
            Select([], prompt="Any camera", id="f-camera", compact=True),
            Select([], prompt="Any developer", id="f-dev", compact=True),
            Select([], prompt="Any year", id="f-year", compact=True),
            Select([], prompt="Any tag", id="f-tag", compact=True),
        ]

    def on_mount(self) -> None:
        self.refresh_filter_options()
        super().on_mount()

    def refresh_filter_options(self) -> None:
        s = self.session
        used_films = {r.film_stock_id for r in roll_service.list_rolls(s)}
        opts = {
            "#f-film": [
                (f.display_name, f.id) for f in catalogue.film_stocks(s) if f.id in used_films
            ],
            "#f-camera": camera_options(s),
            "#f-dev": chem_options(s, [ChemicalKind.FILM_DEVELOPER]),
            "#f-year": [(str(y), y) for y in roll_service.roll_years(s)],
            "#f-tag": [(t.name, t.id) for t in roll_service.all_tags(s)],
        }
        for sid, o in opts.items():
            sel = self.query_one(sid, Select)
            cur = select_value(sel)
            with sel.prevent(Select.Changed):
                sel.set_options(o)
                if cur in [v for _, v in o]:
                    sel.value = cur

    def fetch(self) -> Sequence[Any]:
        def val(sid: str) -> Any:
            return select_value(self.query_one(sid, Select))

        flt = roll_service.RollFilter(
            status=val("#f-status"),
            film_stock_id=val("#f-film"),
            camera_id=val("#f-camera"),
            developer_id=val("#f-dev"),
            year=val("#f-year"),
            tag_id=val("#f-tag"),
        )
        return roll_service.list_rolls(self.session, flt)

    def open_item(self, obj: Any) -> None:
        self.app.push_screen(RollScreen(obj))

    def new_item(self) -> None:
        def saved(roll: Roll) -> None:
            self.app.push_screen(RollScreen(roll))

        new_roll(self.tui, on_saved=saved)

    def delete_item(self, obj: Any) -> None:
        def answer(ok: bool | None) -> None:
            if ok:
                records.delete_roll(self.session, obj)
                self.tui.data_changed()
                self.app.notify("Roll deleted.")

        self.app.push_screen(ConfirmScreen(records.roll_delete_question(obj), yes="Delete"), answer)
