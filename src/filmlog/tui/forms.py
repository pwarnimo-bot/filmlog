# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dialogs: a declarative form dialog, confirmation and text prompts.

A form is described by a list of :class:`Field`. Values go in and come out as
Python values (seconds, dates, °C, …); the dialog shows them in the user's units
and validates inline: errors appear in red under the field, never as pop-ups.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from filmlog.cli.common import (
    CliError,
    parse_date,
    parse_float,
    parse_int,
    parse_stops,
    parse_temp,
    parse_time,
)
from filmlog.services.timefmt import format_duration
from filmlog.services.units import from_display_length, to_display_length, to_display_temp

NEW = "__new__"  # select option that creates a new catalogue entry

RATING_OPTIONS: list[tuple[str, Any]] = [("★" * n + "☆" * (5 - n), n) for n in range(1, 6)]


class CustomInput(Protocol):
    def get_value(self) -> Any: ...
    def set_value(self, value: Any) -> None: ...


@dataclass
class Field:
    """One form row. ``kind``: text, area, int, float, time, date, temp, length,
    stops, select, bool, section, custom."""

    key: str
    label: str
    kind: str = "text"
    options: Sequence[tuple[str, Any]] = ()
    required: bool = False
    placeholder: str = ""
    suggestions: Sequence[str] = ()
    factory: Callable[[], Widget] | None = None  # for kind == "custom"
    allow_blank: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def _fmt_num(v: float | None) -> str:
    return "" if v is None else f"{v:g}"


class FormScreen(ModalScreen[dict[str, Any] | None]):
    """Modal form. Dismisses with the parsed values, or None when cancelled."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]
    DEFAULT_CSS = """
    FormScreen { align: center middle; }
    FormScreen #box {
        width: 104; max-width: 100%; height: 95%;
        border: thick $primary; background: $surface; padding: 0 1;
    }
    FormScreen #title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    FormScreen #note { color: $warning; padding: 0 0 1 0; }
    FormScreen #note.-empty { display: none; }
    FormScreen .row { height: auto; margin: 0 0 0 0; }
    FormScreen .lbl { width: 20; padding: 0 1 0 0; text-align: right; color: $text-muted; }
    FormScreen .lbl.-required { color: $text; text-style: bold; }
    FormScreen .ctl { width: 1fr; height: auto; }
    FormScreen .section { text-style: bold; color: $accent; padding: 1 0 0 0; }
    FormScreen .err { color: $error; height: auto; }
    FormScreen .err.-empty { display: none; }
    FormScreen .hint { color: $text-muted; height: auto; }
    FormScreen TextArea { height: 5; }
    FormScreen #buttons { height: auto; padding: 1 0 0 0; align-horizontal: right; }
    FormScreen #buttons Button { margin: 0 0 0 1; }
    FormScreen #form-error { color: $error; width: 1fr; }
    """

    def __init__(
        self,
        title: str,
        fields: Sequence[Field],
        values: dict[str, Any],
        *,
        temp_unit: str = "C",
        length_unit: str = "cm",
        note: str = "",
        validate: Callable[[dict[str, Any]], dict[str, str]] | None = None,
        on_change: Callable[[FormScreen, str], None] | None = None,
        buttons: Sequence[tuple[str, str, Callable[[FormScreen], None]]] = (),
        save_label: str = "Save",
    ) -> None:
        super().__init__()
        self.form_title = title
        self.fields = [f for f in fields]
        self.by_key = {f.key: f for f in self.fields if f.kind != "section"}
        self.values = dict(values)
        self.temp_unit = temp_unit
        self.length_unit = length_unit
        self.note = note
        self.validate_fn = validate
        self.on_change_fn = on_change
        self.extra_buttons = list(buttons)
        self.save_label = save_label
        self._last: dict[str, Any] = {}
        self._initial: dict[str, Any] = {}

    # -- building ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(self.form_title, id="title")
            yield Static(self.note, id="note", classes="" if self.note else "-empty")
            with VerticalScroll(id="fields"):
                for f in self.fields:
                    if f.kind == "section":
                        yield Static(f.label, classes="section")
                        continue
                    with Horizontal(classes="row"):
                        unit = {"temp": f" (°{self.temp_unit})", "length": f" ({self.length_unit})"}
                        lbl = Label(f.label + unit.get(f.kind, ""), classes="lbl")
                        if f.required:
                            lbl.add_class("-required")
                        yield lbl
                        with Vertical(classes="ctl"):
                            yield self._widget(f)
                            if f.placeholder and f.kind in ("select", "custom", "area"):
                                yield Static(f.placeholder, classes="hint")
                            yield Static("", id=f"e-{f.key}", classes="err -empty")
            with Horizontal(id="buttons"):
                yield Static("", id="form-error")
                for label, bid, _cb in self.extra_buttons:
                    yield Button(label, id=f"x-{bid}")
                yield Button("Cancel", id="cancel")
                yield Button(self.save_label, id="save", variant="primary")

    def _widget(self, f: Field) -> Widget:
        wid = f"f-{f.key}"
        value = self.values.get(f.key)
        if f.kind == "area":
            return TextArea(value or "", id=wid, soft_wrap=True)
        if f.kind == "bool":
            return Checkbox("", bool(value), id=wid, compact=True)
        if f.kind == "select":
            opts = list(f.options)
            known = [v for _, v in opts]
            return Select(
                opts,
                id=wid,
                allow_blank=f.allow_blank or value not in known,
                value=value if value in known else Select.NULL,
                prompt="—",
                compact=True,
            )
        if f.kind == "custom":
            assert f.factory is not None
            w = f.factory()
            w.id = wid
            return w
        suggester = SuggestFromList(f.suggestions, case_sensitive=False) if f.suggestions else None
        return Input(
            self._display(f, value),
            placeholder=f.placeholder or self._default_placeholder(f),
            id=wid,
            suggester=suggester,
            compact=True,
        )

    def _default_placeholder(self, f: Field) -> str:
        return {
            "time": "m:ss — e.g. 8:30, 90, 1m30s",
            "date": "YYYY-MM-DD, today, yesterday",
            "temp": f"°{self.temp_unit}",
            "length": self.length_unit,
            "stops": "e.g. +1, -1, +1/3",
        }.get(f.kind, "")

    def _display(self, f: Field, value: Any) -> str:
        if value is None:
            return ""
        if f.kind == "time":
            return format_duration(value)
        if f.kind == "date":
            return value.isoformat() if isinstance(value, dt.date) else str(value)
        if f.kind == "temp":
            return _fmt_num(to_display_temp(value, self.temp_unit))
        if f.kind == "length":
            return _fmt_num(to_display_length(value, self.length_unit))
        if f.kind == "stops":
            return "0" if round(value * 3) == 0 else f"{value:+g}"
        if f.kind in ("float",):
            return _fmt_num(value)
        return str(value)

    def on_mount(self) -> None:
        for f in self.by_key.values():
            if f.kind == "custom":
                self.custom(f.key).set_value(self.values.get(f.key))
        self._initial = {k: self.raw(k) for k in self.by_key}
        self._last = dict(self._initial)
        first = next(iter(self.by_key), None)
        if first:
            self.query_one(f"#f-{first}").focus()

    # -- raw access (used by on_change handlers) ---------------------------------

    def widget(self, key: str) -> Widget:
        return self.query_one(f"#f-{key}")

    def custom(self, key: str) -> CustomInput:
        return self.widget(key)  # type: ignore[return-value]

    def raw(self, key: str) -> Any:
        f = self.by_key[key]
        w = self.widget(key)
        if isinstance(w, Input):
            return w.value
        if isinstance(w, TextArea):
            return w.text
        if isinstance(w, Checkbox):
            return w.value
        if isinstance(w, Select):
            return None if w.value is Select.NULL or w.value is Select.BLANK else w.value
        if f.kind == "custom":
            return self.custom(key).get_value()
        return None

    def set_raw(self, key: str, value: Any) -> None:
        """Set a field from a Python value (formatted for display)."""
        f = self.by_key[key]
        w = self.widget(key)
        if isinstance(w, Input):
            text = self._display(f, value)
            self._last[key] = text
            w.value = text
        elif isinstance(w, TextArea):
            self._last[key] = value or ""
            w.text = value or ""
        elif isinstance(w, Checkbox):
            self._last[key] = bool(value)
            w.value = bool(value)
        elif isinstance(w, Select):
            self._last[key] = value
            w.value = value if value is not None else Select.NULL
        elif f.kind == "custom":
            self.custom(key).set_value(value)

    def set_options(self, key: str, options: Sequence[tuple[str, Any]], value: Any) -> None:
        w = self.widget(key)
        assert isinstance(w, Select)
        self.by_key[key].options = list(options)
        w.set_options(options)
        self.set_raw(key, value)

    def value(self, key: str) -> Any:
        """Parsed value of one field; None if empty or invalid."""
        try:
            return self._parse(self.by_key[key], self.raw(key))
        except CliError:
            return None

    def set_error(self, key: str, message: str | None) -> None:
        err = self.query_one(f"#e-{key}", Static)
        err.update(message or "")
        err.set_class(not message, "-empty")

    def set_note(self, text: str) -> None:
        note = self.query_one("#note", Static)
        note.update(text)
        note.set_class(not text, "-empty")

    # -- change tracking ---------------------------------------------------------

    def _changed(self, widget_id: str | None) -> None:
        if not widget_id or not widget_id.startswith("f-") or not self._last:
            return
        key = widget_id[2:]
        if key not in self.by_key:
            return
        now = self.raw(key)
        if self._last.get(key) == now:
            return  # programmatic update already known
        self._last[key] = now
        self.set_error(key, None)
        if self.on_change_fn is not None:
            self.on_change_fn(self, key)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._changed(event.input.id)

    def on_select_changed(self, event: Select.Changed) -> None:
        self._changed(event.select.id)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        self._changed(event.checkbox.id)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._changed(event.text_area.id)

    def notify_custom_changed(self, key: str) -> None:
        """Custom widgets call this after the user edits them."""
        self._last[key] = object()  # force a change
        self._changed(f"f-{key}")

    @property
    def dirty(self) -> bool:
        if not self._initial:
            return False
        for k in self.by_key:
            if self.by_key[k].kind == "custom":
                if getattr(self.widget(k), "dirty", False):
                    return True
            elif self.raw(k) != self._initial.get(k):
                return True
        return False

    # -- saving ------------------------------------------------------------------

    def _parse(self, f: Field, raw: Any) -> Any:
        kind = f.kind
        if kind in ("text",):
            return (raw or "").strip()
        if kind in ("area", "bool", "select", "custom"):
            return raw
        text = (raw or "").strip()
        if kind == "int":
            return parse_int(text, f.label.lower()) if text else None
        if kind == "float":
            return parse_float(text, f.label.lower()) if text else None
        if kind == "time":
            return parse_time(text) if text else None
        if kind == "date":
            return parse_date(text) if text else None
        if kind == "temp":
            return parse_temp(text, self.temp_unit) if text else None
        if kind == "length":
            v = parse_float(text, f.label.lower()) if text else None
            return from_display_length(v, self.length_unit)
        if kind == "stops":
            return parse_stops(text) if text else 0.0
        return raw

    def collect(self) -> tuple[dict[str, Any], dict[str, str]]:
        out: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for key, f in self.by_key.items():
            try:
                v = self._parse(f, self.raw(key))
            except CliError as exc:
                errors[key] = str(exc)
                continue
            if f.required and (v is None or v == ""):
                errors[key] = f"{f.label} is required."
            out[key] = v
        if not errors and self.validate_fn is not None:
            errors.update(self.validate_fn(out))
        return out, errors

    def action_save(self) -> None:
        values, errors = self.collect()
        for key in self.by_key:
            self.set_error(key, errors.get(key))
        msg = self.query_one("#form-error", Static)
        if errors:
            msg.update("Please fix the fields marked in red.")
            first = next(iter(errors))
            if first in self.by_key:
                self.widget(first).focus()
            return
        msg.update("")
        self.dismiss(values)

    def action_cancel(self) -> None:
        if not self.dirty:
            self.dismiss(None)
            return

        def answer(discard: bool | None) -> None:
            if discard:
                self.dismiss(None)

        self.app.push_screen(
            ConfirmScreen("Discard your changes?", yes="Discard", no="Keep editing"), answer
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        event.stop()
        if bid == "save":
            self.action_save()
        elif bid == "cancel":
            self.action_cancel()
        elif bid.startswith("x-"):
            for _label, key, cb in self.extra_buttons:
                if f"x-{key}" == bid:
                    cb(self)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes", show=False),
        Binding("n", "no", "No", show=False),
        Binding("escape", "no", "Cancel"),
    ]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen #box {
        width: 72; max-width: 100%; height: auto; border: thick $warning;
        background: $surface; padding: 1 2;
    }
    ConfirmScreen #buttons { height: auto; padding: 1 0 0 0; align-horizontal: right; }
    ConfirmScreen Button { margin: 0 0 0 1; }
    """

    def __init__(self, message: str, *, yes: str = "Yes", no: str = "No") -> None:
        super().__init__()
        self.message = message
        self.yes_label = yes
        self.no_label = no

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(self.message)
            with Horizontal(id="buttons"):
                yield Button(self.no_label, id="no")
                yield Button(self.yes_label, id="yes", variant="warning")

    def on_mount(self) -> None:
        self.query_one("#no").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class PromptScreen(ModalScreen[str | None]):
    """Ask for one line of text (e.g. a file name)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    PromptScreen { align: center middle; }
    PromptScreen #box {
        width: 90; max-width: 100%; height: auto; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    PromptScreen #buttons { height: auto; padding: 1 0 0 0; align-horizontal: right; }
    PromptScreen Button { margin: 0 0 0 1; }
    """

    def __init__(self, message: str, value: str = "", *, ok: str = "OK") -> None:
        super().__init__()
        self.message = message
        self.initial = value
        self.ok = ok

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(self.message)
            yield Input(self.initial, id="text")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self.ok, id="ok", variant="primary")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value.strip() or None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "ok":
            self.dismiss(self.query_one("#text", Input).value.strip() or None)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
