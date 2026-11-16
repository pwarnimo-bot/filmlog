# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Print form (with the exposure table) and the Prints tab."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Select, Static

from filmlog.db.enums import (
    FILTER_GRADES,
    PAPER_SIZES,
    ChemicalKind,
    ContrastMethod,
    ExposurePurpose,
)
from filmlog.db.models import Print, PrintExposure, Roll
from filmlog.services import prints as print_service
from filmlog.services import records
from filmlog.services.images import delete_unreferenced
from filmlog.services.timefmt import format_seconds
from filmlog.tui.forms import RATING_OPTIONS, ConfirmScreen, Field, FormScreen
from filmlog.tui.listpane import ClickTable, Col, ListPane, chip, select_value
from filmlog.tui.options import (
    chem_options,
    dilution_suggestions,
    enum_options,
    label,
    paper_options,
)
from filmlog.tui.records import apply_values, check_image_path, take_image

if TYPE_CHECKING:
    from filmlog.tui.app import FilmLogTUI

_MAIN = (ExposurePurpose.BASE, ExposurePurpose.SOFT, ExposurePurpose.HARD)
EXP_KEYS = ("filter_grade", "seconds", "purpose", "aperture", "note")


def _exp_dict(e: PrintExposure) -> dict[str, Any]:
    return {k: getattr(e, k) for k in EXP_KEYS}


def _as_exposures(rows: Sequence[dict[str, Any]]) -> list[PrintExposure]:
    return [PrintExposure(position=i, **r) for i, r in enumerate(rows)]


class ExposureEditor(Vertical):
    """Ordered exposure rows (base / soft / hard / dodge / burn / flash) with a total."""

    DEFAULT_CSS = """
    ExposureEditor { height: auto; }
    ExposureEditor DataTable { height: auto; max-height: 9; }
    ExposureEditor .bar { height: auto; }
    ExposureEditor .bar Button { margin: 0 1 0 0; min-width: 6; }
    ExposureEditor #total { padding: 0 0 0 1; color: $accent; width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []
        self._initial: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        table = ClickTable(cursor_type="row")
        table.add_columns("#", "Purpose", "Grade", "Time", "Aperture", "Note")
        yield table
        with Horizontal(classes="bar"):
            yield Button("Add", id="exp-add", compact=True)
            yield Button("Edit", id="exp-edit", compact=True)
            yield Button("Remove", id="exp-del", compact=True)
            yield Button("↑", id="exp-up", compact=True)
            yield Button("↓", id="exp-down", compact=True)
            yield Static("", id="total")

    # CustomInput protocol
    def get_value(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows]

    def set_value(self, value: Any) -> None:
        self.rows = [dict(r) for r in (value or [])]
        self._initial = [dict(r) for r in self.rows]
        self._fill()

    @property
    def dirty(self) -> bool:
        return self.rows != self._initial

    def _fill(self, cursor: int | None = None) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for i, r in enumerate(self.rows):
            table.add_row(
                str(i + 1),
                label(r["purpose"]),
                r["filter_grade"],
                format_seconds(r["seconds"]),
                r["aperture"],
                r["note"],
            )
        if cursor is not None and self.rows:
            table.move_cursor(row=max(0, min(cursor, len(self.rows) - 1)))
        total = print_service.total_exposure(_as_exposures(self.rows))
        self.query_one("#total", Static).update(f"Total {format_seconds(total)}")

    def _changed(self, cursor: int | None = None) -> None:
        self._fill(cursor)
        screen = self.screen
        if isinstance(screen, FormScreen) and self.id:
            screen.notify_custom_changed(self.id[2:])

    def _edit(self, index: int | None) -> None:
        row = (
            self.rows[index]
            if index is not None
            else {
                "filter_grade": "2",
                "seconds": None,
                "purpose": ExposurePurpose.BURN,
                "aperture": "",
                "note": "",
            }
        )
        fields = [
            Field("purpose", "Purpose", "select", enum_options(ExposurePurpose), allow_blank=False),
            Field(
                "filter_grade",
                "Filter grade",
                "select",
                [(g, g) for g in FILTER_GRADES],
                allow_blank=False,
            ),
            Field("seconds", "Seconds", "float", required=True, placeholder="e.g. 12.5"),
            Field("aperture", "Aperture", placeholder="only if different, e.g. f/11"),
            Field("note", "Note", placeholder="e.g. burn sky, dodge face"),
        ]

        def done(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            if index is None:
                self.rows.append(result)
                self._changed(len(self.rows) - 1)
            else:
                self.rows[index] = result
                self._changed(index)

        title = "Add exposure" if index is None else f"Exposure {index + 1}"
        self.app.push_screen(FormScreen(title, fields, row), done)

    def _cursor(self) -> int | None:
        table = self.query_one(DataTable)
        if not self.rows or table.cursor_row is None:
            return None
        return table.cursor_row

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if self.screen is not self.app.screen:
            return
        i = self._cursor()
        if i is not None:
            self._edit(i)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if not bid or not bid.startswith("exp-"):
            return
        event.stop()
        i = self._cursor()
        if bid == "exp-add":
            self._edit(None)
        elif i is None:
            return
        elif bid == "exp-edit":
            self._edit(i)
        elif bid == "exp-del":
            del self.rows[i]
            self._changed(i)
        elif bid == "exp-up" and i > 0:
            self.rows[i - 1], self.rows[i] = self.rows[i], self.rows[i - 1]
            self._changed(i - 1)
        elif bid == "exp-down" and i < len(self.rows) - 1:
            self.rows[i + 1], self.rows[i] = self.rows[i], self.rows[i + 1]
            self._changed(i + 1)


def print_fields(app: FilmLogTUI, p: Print, *, roll_select: bool) -> list[Field]:
    s = app.session
    fields: list[Field] = []
    if roll_select:
        from filmlog.services.rolls import list_rolls

        rolls = [(f"{r.code}  {r.title}".strip(), r.id) for r in list_rolls(s)]
        fields.append(Field("roll_id", "Roll", "select", rolls, required=True))
    image_hint = f"current: {p.image} — " if p.image else ""
    fields += [
        Field("frame", "Frame", placeholder="e.g. 12 or 12A"),
        Field("title", "Title"),
        Field("date_printed", "Date printed", "date"),
        Field("paper_id", "Paper", "select", paper_options(s, p.paper_id)),
        Field(
            "paper_size",
            "Paper size",
            suggestions=list(PAPER_SIZES),
            placeholder="e.g. 18×24 cm (→ completes)",
        ),
        Field("enlarger", "Enlarger"),
        Field("enlarging_lens", "Enlarging lens"),
        Field("aperture", "Aperture", placeholder="e.g. f/8"),
        Field("head_height_cm", "Head height", "length"),
        Field("exp", "Exposure", "section"),
        Field(
            "contrast_method",
            "Contrast method",
            "select",
            enum_options(ContrastMethod),
            allow_blank=False,
        ),
        Field(
            "exposures",
            "Exposures",
            "custom",
            factory=ExposureEditor,
            placeholder="Enter/click a row to edit. Dodges don't add to the total.",
        ),
        Field("proc", "Processing", "section"),
        Field(
            "developer_id",
            "Developer",
            "select",
            chem_options(s, [ChemicalKind.PAPER_DEVELOPER], p.developer_id),
        ),
        Field("dev_dilution", "Dilution", suggestions=dilution_suggestions(s, p.developer_id)),
        Field("dev_time_s", "Dev time", "time"),
        Field("dev_temperature_c", "Temperature", "temp"),
        Field(
            "stop_chemical_id",
            "Stop bath",
            "select",
            chem_options(s, [ChemicalKind.STOP_BATH], p.stop_chemical_id),
        ),
        Field("stop_time_s", "Stop time", "time"),
        Field("fixer_id", "Fixer", "select", chem_options(s, [ChemicalKind.FIXER], p.fixer_id)),
        Field("fixer_dilution", "Fixer dilution", suggestions=dilution_suggestions(s, p.fixer_id)),
        Field("fix_time_s", "Fix time", "time"),
        Field("wash_time_s", "Wash time", "time"),
        Field("toning", "Toning", placeholder="e.g. Selenium 1+9, 3 min"),
        Field("result", "Result", "section"),
        Field("is_final", "Final print", "bool"),
        Field("rating", "Rating", "select", RATING_OPTIONS),
        Field("image_path", "Attach image", placeholder=f"{image_hint}path to a scan or photo"),
        Field("notes", "Notes", "area"),
    ]
    return fields


_VALUE_KEYS = (
    "roll_id",
    "frame",
    "title",
    "date_printed",
    "paper_id",
    "paper_size",
    "enlarger",
    "enlarging_lens",
    "aperture",
    "head_height_cm",
    "contrast_method",
    "developer_id",
    "dev_dilution",
    "dev_time_s",
    "dev_temperature_c",
    "stop_chemical_id",
    "stop_time_s",
    "fixer_id",
    "fixer_dilution",
    "fix_time_s",
    "wash_time_s",
    "toning",
    "is_final",
    "rating",
    "notes",
)


def open_print_form(
    app: FilmLogTUI,
    p: Print,
    *,
    title: str,
    note: str = "",
    roll_select: bool = False,
    on_saved: Callable[[Print], None] | None = None,
) -> None:
    s = app.session
    values = {k: getattr(p, k) for k in _VALUE_KEYS}
    values["exposures"] = [_exp_dict(e) for e in p.exposures]
    values["image_path"] = ""

    def on_change(form: FormScreen, key: str) -> None:
        if key == "contrast_method":
            rows = form.custom("exposures").get_value()
            method = form.raw("contrast_method")
            if method and not any((r["seconds"] or 0) > 0 for r in rows):
                form.set_raw(
                    "exposures", [_exp_dict(e) for e in print_service.default_exposures(method)]
                )
        elif key in ("developer_id", "fixer_id"):
            from textual.suggester import SuggestFromList
            from textual.widgets import Input

            target = "dev_dilution" if key == "developer_id" else "fixer_dilution"
            w = form.widget(target)
            if isinstance(w, Input):
                w.suggester = SuggestFromList(dilution_suggestions(s, form.raw(key)))

    def validate(v: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        problem = print_service.exposure_problem(
            v["contrast_method"], _as_exposures(v["exposures"])
        )
        if problem:
            errors["exposures"] = problem
        img = check_image_path(v.get("image_path") or "")
        if img:
            errors["image_path"] = img
        return errors

    def done(result: dict[str, Any] | None) -> None:
        if result is None:
            return
        rows = result.pop("exposures")
        image = result.pop("image_path")
        if not roll_select:
            result.pop("roll_id", None)
        old_roll_id = p.roll_id
        with s.no_autoflush:
            apply_values(s, p, result)
            p.exposures = _as_exposures(rows)
            old = None
            if image:
                old, p.image = p.image, take_image(image)
        s.add(p)
        s.commit()
        if old:
            delete_unreferenced(s, [old])
        # Rolls already loaded keep their print lists; reload the affected ones.
        for rid in {old_roll_id, p.roll_id}:
            r = s.get(Roll, rid) if rid else None
            if r is not None:
                s.expire(r, ["prints"])
        app.data_changed()
        app.notify(f"Saved print #{p.id}.")
        if on_saved is not None:
            on_saved(p)

    app.push_screen(
        FormScreen(
            title,
            print_fields(app, p, roll_select=roll_select),
            values,
            note=note,
            temp_unit=app.settings.temperature_unit,
            length_unit=app.settings.length_unit,
            validate=validate,
            on_change=on_change,
        ),
        done,
    )


def new_print(
    app: FilmLogTUI,
    roll: Roll | None,
    on_saved: Callable[[Print], None] | None = None,
) -> None:
    p, src = print_service.new_print_for(app.session, roll)
    note = ""
    if src is not None:
        where = (
            "this roll"
            if roll is not None and src.roll_id == roll.id
            else (f"roll {src.roll.code}")
        )
        note = f"Paper, enlarger and chemistry pre-filled from print #{src.id} ({where})."
    title = f"New print — roll {roll.code}" if roll else "New print"
    open_print_form(app, p, title=title, note=note, roll_select=roll is None, on_saved=on_saved)


def duplicate(app: FilmLogTUI, src: Print, on_saved: Callable[[Print], None] | None = None) -> None:
    # Only roll_id is copied (not the relationship), so a cancelled copy never
    # reaches the session.
    p = print_service.duplicate_print(src)
    open_print_form(
        app,
        p,
        title=f"Copy of print #{src.id} — roll {src.roll.code}",
        note="All settings copied — change what's different for this attempt.",
        on_saved=on_saved,
    )


def edit(app: FilmLogTUI, p: Print, on_saved: Callable[[Print], None] | None = None) -> None:
    title = f"Print #{p.id} — roll {p.roll.code}" + (f", frame {p.frame}" if p.frame else "")
    open_print_form(app, p, title=title, roll_select=True, on_saved=on_saved)


def confirm_delete(app: FilmLogTUI, p: Print, on_done: Callable[[], None] | None = None) -> None:
    what = f"print #{p.id} (roll {p.roll.code}, frame {p.frame or '?'})"

    def answer(ok: bool | None) -> None:
        if ok:
            records.delete_print(app.session, p)
            app.data_changed()
            app.notify(f"Deleted {what}.")
            if on_done is not None:
                on_done()

    extra = " and its image" if p.image else ""
    app.push_screen(ConfirmScreen(f"Delete {what}{extra}?", yes="Delete"), answer)


def print_columns(app: Any, *, with_roll: bool) -> list[Col]:
    cols = [
        Col("Id", lambda p: p.id, sort=lambda p: p.id, right=True, width=4),
    ]
    if with_roll:
        cols.append(Col("Roll", lambda p: p.roll.code, width=9))
    cols += [
        Col("Frame", lambda p: p.frame, width=6),
        Col("Title", lambda p: p.title, width=16),
        Col("Date", lambda p: p.date_printed, width=10),
        Col("Paper", lambda p: p.paper.display_name if p.paper else "", width=30),
        Col("Size", lambda p: p.paper_size, width=9),
        Col(
            "Contrast",
            lambda p: print_service.contrast_summary(p.contrast_method, p.exposures),
            width=30,
        ),
        Col(
            "Total",
            lambda p: format_seconds(print_service.total_exposure(p.exposures)),
            sort=lambda p: print_service.total_exposure(p.exposures),
            right=True,
            width=6,
        ),
        Col("Rating", lambda p: "★" * (p.rating or 0), sort=lambda p: p.rating or 0, width=6),
        Col(
            "Final",
            lambda p: "final" if p.is_final else "",
            sort=lambda p: p.is_final,
            render=lambda p: chip(app, "final" if p.is_final else "", "final"),
            width=7,
        ),
    ]
    return cols


class PrintsPane(ListPane):
    """All prints across rolls."""

    new_label = "New print"
    empty_text = "No prints yet"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.columns = print_columns(self, with_roll=True)

    def filter_widgets(self) -> list[Select[Any]]:
        return [
            Select([], prompt="Any paper", id="f-paper", compact=True),
            Select([], prompt="Any developer", id="f-dev", compact=True),
            Select(
                enum_options(ContrastMethod),
                prompt="Any contrast method",
                id="f-method",
                compact=True,
            ),
            Select(
                [("Final prints only", True)], prompt="Work + final", id="f-final", compact=True
            ),
            Select(
                [(f"{'★' * n} or better", n) for n in range(1, 6)],
                prompt="Any rating",
                id="f-rating",
                compact=True,
            ),
        ]

    def on_mount(self) -> None:
        self.refresh_filter_options()
        super().on_mount()

    def refresh_filter_options(self) -> None:
        s = self.session
        for sid, opts in (
            ("#f-paper", paper_options(s)),
            ("#f-dev", chem_options(s, [ChemicalKind.PAPER_DEVELOPER])),
        ):
            sel = self.query_one(sid, Select)
            cur = select_value(sel)
            with sel.prevent(Select.Changed):
                sel.set_options(opts)
                if cur in [v for _, v in opts]:
                    sel.value = cur

    def fetch(self) -> Sequence[Any]:
        def val(sid: str) -> Any:
            return select_value(self.query_one(sid, Select))

        flt = print_service.PrintFilter(
            paper_id=val("#f-paper"),
            developer_id=val("#f-dev"),
            contrast_method=val("#f-method"),
            final_only=bool(val("#f-final")),
            min_rating=val("#f-rating"),
        )
        return print_service.list_prints(self.session, flt)

    def new_item(self) -> None:
        new_print(self.tui, None, on_saved=lambda p: self.reload(select=p))

    def open_item(self, obj: Any) -> None:
        edit(self.tui, obj, on_saved=lambda p: self.reload(select=p))

    def delete_item(self, obj: Any) -> None:
        confirm_delete(self.tui, obj)
