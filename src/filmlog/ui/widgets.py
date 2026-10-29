# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reusable input widgets: duration, optional date/number, reference combos, chips."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QDate, QSignalBlocker, QStringListModel, Qt, Signal
from PySide6.QtGui import QFocusEvent, QGuiApplication, QValidator
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from filmlog.services import units
from filmlog.services.pushpull import badge_kind, badge_text
from filmlog.services.timefmt import format_duration, parse_duration
from filmlog.ui.labels import label as enum_label
from filmlog.ui.labels import tr as tr_label

# --------------------------------------------------------------------------- fields


class DurationEdit(QLineEdit):
    """Accepts ``90``, ``1:30``, ``1m30s``; displays ``m:ss``. Empty means None."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("m:ss")
        self.setMaximumWidth(110)
        self.setToolTip(self.tr("Enter e.g. 90, 1:30 or 1m30s"))
        self.editingFinished.connect(self._normalise)

    def value(self) -> int | None:
        """Parsed seconds; raises ValueError if the text is invalid."""
        return parse_duration(self.text())

    def is_valid(self) -> bool:
        try:
            self.value()
        except ValueError:
            return False
        return True

    def set_value(self, seconds: int | None) -> None:
        self.setText(format_duration(seconds))

    def _normalise(self) -> None:
        try:
            v = self.value()
        except ValueError:
            return
        formatted = format_duration(v)
        if formatted != self.text():
            self.setText(formatted)


class OptionalDateEdit(QDateEdit):
    """QDateEdit that can be empty (shown as "—"). Press Delete/Backspace to clear."""

    _NULL = QDate(1900, 1, 1)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setMinimumDate(self._NULL)
        self.setSpecialValueText("—")
        self.setDate(self._NULL)
        self.setMaximumWidth(140)

    def value(self) -> dt.date | None:
        d = self.date()
        if d == self._NULL:
            return None
        return dt.date(d.year(), d.month(), d.day())

    def set_value(self, value: dt.date | None) -> None:
        if value is None:
            self.setDate(self._NULL)
        else:
            self.setDate(QDate(value.year, value.month, value.day))

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusInEvent(event)
        if self.date() == self._NULL and self.calendarWidget() is not None:
            self.calendarWidget().setSelectedDate(QDate.currentDate())

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if (
            event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
            and self.currentSectionIndex() == 0
        ):
            self.set_value(None)
            return
        if self.date() == self._NULL and event.text().isdigit():
            self.setDate(QDate.currentDate())
        super().keyPressEvent(event)


class OptionalIntSpin(QSpinBox):
    """Integer spin box whose minimum means "not set"."""

    def __init__(self, minimum: int = 0, maximum: int = 100000, parent: QWidget | None = None):
        super().__init__(parent)
        self.setRange(minimum - 1, maximum)
        self.setSpecialValueText("—")
        self.setValue(minimum - 1)
        self.setMaximumWidth(120)

    def value_or_none(self) -> int | None:
        v = self.value()
        return None if v == self.minimum() else v

    def set_value(self, v: int | None) -> None:
        self.setValue(self.minimum() if v is None else v)


class OptionalDoubleSpin(QDoubleSpinBox):
    def __init__(
        self,
        minimum: float = 0.0,
        maximum: float = 100000.0,
        decimals: int = 1,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setDecimals(decimals)
        step = 10**-decimals
        self.setRange(minimum - step, maximum)
        self.setSpecialValueText("—")
        self.setValue(self.minimum())
        self.setMaximumWidth(130)

    def value_or_none(self) -> float | None:
        v = self.value()
        return None if v <= self.minimum() else v

    def set_value(self, v: float | None) -> None:
        self.setValue(self.minimum() if v is None else v)


class TemperatureSpin(QDoubleSpinBox):
    """Stores °C, displays in the configured unit."""

    def __init__(self, unit: str = "C", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDecimals(1)
        self.setSingleStep(0.5)
        self.setMaximumWidth(120)
        self.set_unit(unit)

    def set_unit(self, unit: str) -> None:
        c = self.celsius() if hasattr(self, "_unit") else 20.0
        self._unit = unit
        if unit == "F":
            self.setRange(32.0, 140.0)
        else:
            self.setRange(0.0, 60.0)
        self.setSuffix(f" °{unit}")
        self.set_celsius(c)

    def celsius(self) -> float:
        v = units.from_display_temp(self.value(), self._unit)
        return 20.0 if v is None else round(v, 2)

    def set_celsius(self, c: float | None) -> None:
        v = units.to_display_temp(20.0 if c is None else c, self._unit)
        self.setValue(v if v is not None else 20.0)


class RatingCombo(QComboBox):
    def __init__(self, labels: Sequence[str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.addItem("—", None)
        names = labels or ("", "", "", "", "")
        for i in range(1, 6):
            extra = f"  {names[i - 1]}" if names[i - 1] else ""
            self.addItem("★" * i + "☆" * (5 - i) + extra, i)

    def value(self) -> int | None:
        v = self.currentData()
        return int(v) if v is not None else None

    def set_value(self, v: int | None) -> None:
        self.setCurrentIndex(max(0, self.findData(v)) if v is not None else 0)


def stars(n: int | None) -> str:
    return "" if not n else "★" * n + "☆" * (5 - n)


# --------------------------------------------------------------------------- combos


class EnumCombo(QComboBox):
    def __init__(self, enum_cls: type[StrEnum], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.enum_cls = enum_cls
        for member in enum_cls:
            self.addItem(enum_label(member), member.value)

    def value(self) -> Any:
        return self.enum_cls(self.currentData())

    def set_value(self, v: StrEnum | None) -> None:
        if v is None:
            self.setCurrentIndex(0)
        else:
            self.setCurrentIndex(max(0, self.findData(v.value)))


NEW_ITEM = "__new__"


class RefCombo(QComboBox):
    """Searchable combo of (id, label) pairs, optional "none" and "+ New…" entries.

    Typing filters by substring. Items may be greyed (e.g. retired cameras) but
    remain selectable.
    """

    newRequested = Signal()  # noqa: N815

    def __init__(
        self,
        *,
        allow_none: bool = True,
        none_label: str = "—",
        new_label: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.allow_none = allow_none
        self.none_label = none_label
        self.new_label = new_label
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumContentsLength(12)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        comp = QCompleter(self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        comp.setModel(self.model())
        comp.activated[str].connect(self._on_completed)  # type: ignore[index]
        self.setCompleter(comp)
        self.activated.connect(self._on_activated)
        if (edit := self.lineEdit()) is not None:
            edit.editingFinished.connect(self._snap_to_item)
        self._last_index = 0

    def set_items(
        self, items: Iterable[tuple[int, str]], greyed: Iterable[int] = (), keep: bool = True
    ) -> None:
        current = self.current_id() if keep else None
        greyed_ids = set(greyed)
        with QSignalBlocker(self):
            self.clear()
            if self.allow_none:
                self.addItem(self.none_label, None)
            for oid, text in items:
                self.addItem(text, oid)
                if oid in greyed_ids:
                    self.setItemData(
                        self.count() - 1,
                        self.palette().placeholderText(),
                        Qt.ItemDataRole.ForegroundRole,
                    )
            if self.new_label:
                self.addItem(self.new_label, NEW_ITEM)
        self.set_current_id(current)

    def current_id(self) -> int | None:
        data = self.currentData()
        if data is None or data == NEW_ITEM:
            return None
        return int(data)

    def set_current_id(self, oid: int | None) -> None:
        with QSignalBlocker(self):
            idx = self.findData(oid) if oid is not None else (0 if self.allow_none else -1)
            if idx < 0:
                idx = 0 if self.count() and self.itemData(0) != NEW_ITEM else -1
            self.setCurrentIndex(idx)
            self._last_index = max(idx, 0)
        self.currentIndexChanged.emit(self.currentIndex())

    def _on_activated(self, index: int) -> None:
        if self.itemData(index) == NEW_ITEM:
            with QSignalBlocker(self):
                self.setCurrentIndex(self._last_index)
            self.newRequested.emit()
        else:
            self._last_index = index

    def _on_completed(self, text: str) -> None:
        idx = self.findText(text)
        if idx >= 0:
            self.setCurrentIndex(idx)
            self._on_activated(idx)

    def _snap_to_item(self) -> None:
        """Typed text that doesn't match an item reverts to the current item."""
        idx = self.findText(self.currentText(), Qt.MatchFlag.MatchFixedString)
        if idx < 0:
            # Accept a unique substring match.
            matches = [
                i
                for i in range(self.count())
                if self.currentText().lower() in self.itemText(i).lower()
                and self.itemData(i) != NEW_ITEM
            ]
            idx = matches[0] if len(matches) == 1 else self._last_index
        if self.itemData(idx) == NEW_ITEM:
            idx = self._last_index
        self.setCurrentIndex(idx)
        self._last_index = idx


def set_completions(edit: QLineEdit, words: Sequence[str]) -> None:
    comp = edit.completer()
    if comp is None:
        comp = QCompleter(edit)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setModel(QStringListModel(edit))
        edit.setCompleter(comp)
    model = comp.model()
    if isinstance(model, QStringListModel):
        model.setStringList(list(words))


# --------------------------------------------------------------------------- chips & badges


class ChipRow(QWidget):
    """A row of small buttons that write their text into a target line edit."""

    picked = Signal(str)

    def __init__(self, target: QLineEdit | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.target = target
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)

    def set_chips(self, values: Sequence[str]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        for v in values:
            b = QPushButton(v)
            b.setProperty("role", "chip")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep tab order on real fields
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=v: self._pick(v))
            self._layout.addWidget(b)
        self._layout.addStretch(1)

    def _pick(self, value: str) -> None:
        if self.target is not None:
            self.target.setText(value)
            self.target.setFocus()
        self.picked.emit(value)


BADGE_COLOURS = {
    "push": ("#b45309", "#ffffff"),
    "pull": ("#1d4ed8", "#ffffff"),
    "box": ("#6b7280", "#ffffff"),
    "loaded": ("#7c3aed", "#ffffff"),
    "exposed": ("#b45309", "#ffffff"),
    "developed": ("#15803d", "#ffffff"),
    "final": ("#15803d", "#ffffff"),
    "expired": ("#b91c1c", "#ffffff"),
}


def chip_colours(kind: str) -> tuple[str, str]:
    from filmlog.ui.theme import current_theme

    if current_theme() == "darkroom":
        return "#2a0404", "#c02020"
    return BADGE_COLOURS.get(kind, ("#6b7280", "#ffffff"))


def badge_style(kind: str) -> str:
    bg, fg = chip_colours(kind)
    return f"background:{bg}; color:{fg};"


class Badge(QLabel):
    def __init__(self, text: str = "", kind: str = "box", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "badge")
        self.set(text, kind)

    def set(self, text: str, kind: str) -> None:
        self.setText(text)
        self.setStyleSheet(badge_style(kind))
        self.setVisible(bool(text))


def push_pull_badge(stops: float) -> tuple[str, str]:
    """Translated badge text and colour kind for a push/pull value."""
    kind = badge_kind(stops)
    if kind == "box":
        return tr_label("Box speed"), kind
    word, _, rest = badge_text(stops).partition(" ")
    return f"{tr_label(word)} {rest}", kind


# --------------------------------------------------------------------------- forms


class Field:
    """A form row: widget + inline red hint label underneath."""

    def __init__(self, widget: QWidget, hint: QLabel, container: QWidget) -> None:
        self.widget = widget
        self.hint = hint
        self.container = container

    def set_error(self, message: str | None) -> bool:
        self.hint.setText(message or "")
        self.hint.setVisible(bool(message))
        return not message


class FormBuilder:
    """QFormLayout wrapper keeping visual = tab order and hint labels per field."""

    def __init__(self, layout: QFormLayout | None = None) -> None:
        self.layout = layout or QFormLayout()
        self.layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # In narrow panes labels move above their fields instead of forcing width.
        self.layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._focus_chain: list[QWidget] = []

    def add(self, text: str, widget: QWidget | QLayout, *focusables: QWidget) -> Field:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        if isinstance(widget, QLayout):
            v.addLayout(widget)
            main: QWidget = focusables[0] if focusables else container
        else:
            v.addWidget(widget)
            main = widget
        hint = QLabel()
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        hint.hide()
        v.addWidget(hint)
        self.layout.addRow(text, container)
        self._focus_chain.extend(focusables or (main,))
        return Field(main, hint, container)

    def section(self, title: str) -> None:
        lbl = QLabel(f"<b>{title}</b>")
        lbl.setContentsMargins(0, 8, 0, 0)
        self.layout.addRow(lbl)

    def finish(self) -> list[QWidget]:
        chain = self._focus_chain
        for a, b in zip(chain, chain[1:], strict=False):
            QWidget.setTabOrder(a, b)
        return chain


def fit_to_screen(widget: QWidget, width: int, height: int, margin: int = 48) -> None:
    """Resize ``widget`` to width×height, but never beyond the available screen."""
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        width = min(width, avail.width() - margin)
        height = min(height, avail.height() - margin)
    widget.resize(width, height)


def row(*widgets: QWidget | str, stretch: bool = True) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        if isinstance(w, str):
            h.addWidget(QLabel(w))
        else:
            h.addWidget(w)
    if stretch:
        h.addStretch(1)
    return h


def connect_changed(widgets: Iterable[QWidget], slot: Callable[[], None]) -> None:
    """Connect each widget's "value changed" signal to ``slot`` (for dirty tracking)."""
    from PySide6.QtWidgets import QAbstractButton, QPlainTextEdit, QTextEdit

    for w in widgets:
        if isinstance(w, QLineEdit):
            w.textEdited.connect(slot)
        elif isinstance(w, QComboBox):
            w.currentIndexChanged.connect(slot)
            if w.isEditable() and (edit := w.lineEdit()) is not None:
                edit.textEdited.connect(slot)
        elif isinstance(w, QSpinBox | QDoubleSpinBox):
            w.valueChanged.connect(slot)
        elif isinstance(w, QDateEdit):
            w.dateChanged.connect(slot)
        elif isinstance(w, QPlainTextEdit | QTextEdit):
            w.textChanged.connect(slot)
        elif isinstance(w, QAbstractButton):
            w.toggled.connect(slot)


# --------------------------------------------------------------------------- special fields


class StopsSpin(QDoubleSpinBox):
    """Push/pull in ⅓-stop steps, shown as "+1⅓", "−⅔", "0"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(-5.0, 5.0)
        self.setDecimals(2)
        self.setSingleStep(1 / 3)
        self.setMaximumWidth(100)
        self.setToolTip(self.tr("Push/pull in stops; calculated from EI ÷ box ISO, editable"))

    def textFromValue(self, value: float) -> str:  # noqa: N802
        from filmlog.services.pushpull import format_stops

        return format_stops(value)

    def valueFromText(self, text: str) -> float:  # noqa: N802
        v = parse_stops(text)
        return 0.0 if v is None else v

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        if parse_stops(text) is not None:
            return QValidator.State.Acceptable, text, pos
        return QValidator.State.Intermediate, text, pos

    def stepBy(self, steps: int) -> None:  # noqa: N802
        from filmlog.services.pushpull import round_to_third

        self.setValue(round_to_third(self.value() + steps / 3))


def parse_stops(text: str) -> float | None:
    import re

    t = text.strip().replace("−", "-").replace(" ", "").replace(",", ".")
    if not t:
        return None
    m = re.fullmatch(r"([+-]?)(\d*)([⅓⅔]?)", t)
    if m and (m.group(2) or m.group(3)):
        whole = int(m.group(2) or 0)
        frac = {"": 0.0, "⅓": 1 / 3, "⅔": 2 / 3}[m.group(3)]
        v = whole + frac
        return round(-v if m.group(1) == "-" else v, 2)
    try:
        return round(float(t), 2)
    except ValueError:
        return None


class ListCompleter(QCompleter):
    """Completes the last item of a comma-separated list (tags, roll codes)."""

    def __init__(self, words: Sequence[str], edit: QLineEdit) -> None:
        super().__init__(list(words), edit)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterMode(Qt.MatchFlag.MatchContains)
        self._edit = edit
        edit.setCompleter(self)

    def set_words(self, words: Sequence[str]) -> None:
        model = self.model()
        if isinstance(model, QStringListModel):
            model.setStringList(list(words))

    def splitPath(self, path: str) -> list[str]:  # noqa: N802
        return [path.split(",")[-1].strip()]

    def pathFromIndex(self, index: Any) -> str:  # noqa: N802
        chosen = super().pathFromIndex(index)
        parts = [p.strip() for p in self._edit.text().split(",")]
        parts[-1] = chosen
        return ", ".join(p for p in parts if p) + ", "
