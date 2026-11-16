# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""A searchable, sortable list of records. Clicking a row (or Enter) opens it."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Select

from filmlog.cli.common import fmt

if TYPE_CHECKING:
    from filmlog.tui.app import FilmLogTUI

CHIP_STYLES = {
    "loaded": "bold white on #7c3aed",
    "exposed": "bold white on #c2410c",
    "developed": "bold white on #15803d",
    "push": "bold white on #c2410c",
    "pull": "bold white on #1d4ed8",
    "box": "white on #4b5563",
    "final": "bold white on #15803d",
    "dim": "dim",
}


def chip(app: Any, text: str, kind: str) -> Text:
    """A coloured label; plain red in the Darkroom theme (no bright colours)."""
    if not text:
        return Text("")
    if getattr(app, "theme", "") == "darkroom":
        return Text(f"[{text}]", style="bold #b00000")
    return Text(f" {text} ", style=CHIP_STYLES.get(kind, ""))


class ClickTable(DataTable[Any]):
    """Row table where a single click opens the row (Textual needs a second click)."""

    async def _on_click(self, event: events.Click) -> None:
        meta = event.style.meta
        before = self.cursor_coordinate
        await super()._on_click(event)
        row, col = meta.get("row", -1), meta.get("column", -1)
        if "row" in meta and row >= 0 and col >= 0 and self.cursor_coordinate != before:
            self._post_selected_message()


@dataclass
class Col:
    header: str
    get: Callable[[Any], Any]
    sort: Callable[[Any], Any] | None = None
    render: Callable[[Any], Any] | None = None  # Rich renderable instead of text
    width: int | None = None
    right: bool = False


class ListPane(Vertical):
    """Subclasses define ``columns``, ``fetch``, ``open_item``, ``new_item``, ``delete_item``."""

    BINDINGS = [
        Binding("delete", "delete", "Delete"),
        Binding("ctrl+n", "new", "New"),
    ]
    DEFAULT_CSS = """
    ListPane { height: 1fr; }
    ListPane .toolbar { height: auto; padding: 0 0 1 0; }
    ListPane .toolbar Input { width: 1fr; }
    ListPane .toolbar Button { margin: 0 0 0 1; min-width: 10; }
    ListPane .filters { height: auto; padding: 0 0 1 0; }
    ListPane .filters Select { width: 1fr; margin: 0 1 0 0; }
    ListPane .filters.-none { display: none; }
    ListPane DataTable { height: 1fr; }
    """
    new_label = "New"
    empty_text = "Nothing here yet."
    show_search = True
    # Extra toolbar buttons: (label, css class); pressing one calls ``extra_action(cls)``.
    extra_buttons: Sequence[tuple[str, str]] = ()

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.items: list[Any] = []
        self._shown: list[Any] = []
        self._sort_col: int | None = None
        self._sort_reverse = False

    @property
    def tui(self) -> FilmLogTUI:
        return self.app  # type: ignore[return-value]

    @property
    def session(self) -> Any:
        return self.tui.session

    # -- to implement -------------------------------------------------------------

    columns: Sequence[Col] = ()

    def fetch(self) -> Sequence[Any]:
        raise NotImplementedError

    def filter_widgets(self) -> list[Select[Any]]:
        return []

    def open_item(self, obj: Any) -> None:
        pass

    def new_item(self) -> None:
        pass

    def delete_item(self, obj: Any) -> None:
        pass

    def item_dimmed(self, obj: Any) -> bool:
        return False

    # -- layout -------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            search = Input(placeholder="Search…  (ctrl+f)", classes="search", compact=True)
            search.display = self.show_search
            yield search
            yield Button(self.new_label, classes="new", variant="primary", compact=True)
            yield Button("Open", classes="open", compact=True)
            for text, cls in self.extra_buttons:
                yield Button(text, classes=f"extra {cls}", compact=True)
            yield Button("Delete", classes="delete", variant="error", compact=True)
        filters = self.filter_widgets()
        with Horizontal(classes="filters" + ("" if filters else " -none")):
            yield from filters
        table = ClickTable(cursor_type="row", zebra_stripes=True)
        yield table

    def on_mount(self) -> None:
        table = self.table
        for c in self.columns:
            table.add_column(c.header, width=c.width)
        self.reload()

    @property
    def table(self) -> DataTable[Any]:
        return self.query_one(DataTable)

    @property
    def search_text(self) -> str:
        return self.query_one(".search", Input).value

    def focus_search(self) -> None:
        self.query_one(".search", Input).focus()

    # -- data ---------------------------------------------------------------------

    def reload(self, select: Any = None) -> None:
        """Re-read the records; keep the cursor on ``select`` if listed, else where it was."""
        current = self.current()
        self.items = list(self.fetch())
        self._fill(select if select is not None and select in self.items else current)

    def _cell(self, c: Col, obj: Any, dim: bool) -> Any:
        if c.render is not None:
            return c.render(obj)
        text = fmt(c.get(obj))
        t = Text(text, style="dim" if dim else "")
        if c.right:
            t.justify = "right"
        return t

    def _fill(self, keep: Any = None) -> None:
        words = self.search_text.lower().split()
        shown = []
        for obj in self.items:
            if words:
                hay = " ".join(fmt(c.get(obj)) for c in self.columns).lower()
                if not all(w in hay for w in words):
                    continue
            shown.append(obj)
        if self._sort_col is not None:
            col = self.columns[self._sort_col]

            def text_key(o: Any) -> str:
                return fmt(col.get(o)).lower()

            shown.sort(key=col.sort or text_key, reverse=self._sort_reverse)
        self._shown = shown
        table = self.table
        table.clear()
        for obj in shown:
            dim = self.item_dimmed(obj)
            table.add_row(*(self._cell(c, obj, dim) for c in self.columns), key=str(id(obj)))
        if keep is not None and keep in shown:
            table.move_cursor(row=shown.index(keep))
        table.border_subtitle = f"{len(shown)} of {len(self.items)}" if self.items else ""
        if not self.items:
            table.border_subtitle = self.empty_text

    def current(self) -> Any:
        table = self.table
        if not self._shown or table.cursor_row is None:
            return None
        if 0 <= table.cursor_row < len(self._shown):
            return self._shown[table.cursor_row]
        return None

    # -- events -------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.has_class("search"):
            event.stop()
            self._fill(self.current())

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.parent is not None and event.select.parent.has_class("filters"):
            event.stop()
            self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if self.screen is not self.app.screen:
            return  # a second click event while the record is already open
        obj = self.current()
        if obj is not None:
            self.open_item(obj)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        event.stop()
        if self._sort_col == event.column_index:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col, self._sort_reverse = event.column_index, False
        self._fill(self.current())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        b = event.button
        if b.has_class("new"):
            event.stop()
            self.new_item()
        elif b.has_class("open"):
            event.stop()
            obj = self.current()
            if obj is not None:
                self.open_item(obj)
        elif b.has_class("delete"):
            event.stop()
            self.action_delete()
        elif b.has_class("extra"):
            event.stop()
            for _text, cls in self.extra_buttons:
                if b.has_class(cls):
                    self.extra_action(cls)

    def extra_action(self, cls: str) -> None:
        pass

    def action_delete(self) -> None:
        obj = self.current()
        if obj is not None:
            self.delete_item(obj)

    def action_new(self) -> None:
        self.new_item()


def select_value(sel: Select[Any]) -> Any:
    v = sel.value
    return None if v is Select.NULL or v is Select.BLANK else v
