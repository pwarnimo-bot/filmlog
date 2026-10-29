# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Print form with the ordered exposure table (single / split grade / dodge / burn)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from filmlog.db.enums import (
    FILTER_GRADES,
    PAPER_SIZES,
    ChemicalKind,
    ContrastMethod,
    ExposurePurpose,
)
from filmlog.db.models import Chemical, Paper, Print, PrintExposure, Roll
from filmlog.services import catalogue as cat
from filmlog.services.images import delete_unreferenced
from filmlog.services.prints import default_exposures, new_print_for
from filmlog.services.timefmt import format_seconds
from filmlog.services.units import from_display_length, to_display_length
from filmlog.ui.catalogue_view import notes_edit
from filmlog.ui.context import AppContext
from filmlog.ui.development_form import chemical_items, dilution_chips
from filmlog.ui.editor import EditorForm
from filmlog.ui.images import ImageField, forget_thumbnail
from filmlog.ui.labels import label
from filmlog.ui.widgets import (
    ChipRow,
    DurationEdit,
    EnumCombo,
    FormBuilder,
    OptionalDateEdit,
    OptionalDoubleSpin,
    RatingCombo,
    RefCombo,
    TemperatureSpin,
    row,
)

AnyIndex = QModelIndex | QPersistentModelIndex


def _tr(text: str) -> str:
    return QCoreApplication.translate("Prints", text)


# --------------------------------------------------------------------------- exposure table


@dataclass
class ExposureRow:
    purpose: ExposurePurpose = ExposurePurpose.BASE
    filter_grade: str = "2"
    seconds: float = 0.0
    aperture: str = ""
    note: str = ""

    @classmethod
    def from_model(cls, e: PrintExposure) -> ExposureRow:
        return cls(
            e.purpose or ExposurePurpose.BASE,
            e.filter_grade or "none",
            e.seconds or 0.0,
            e.aperture or "",
            e.note or "",
        )

    def to_model(self, position: int) -> PrintExposure:
        return PrintExposure(
            position=position,
            purpose=self.purpose,
            filter_grade=self.filter_grade,
            seconds=round(self.seconds, 2),
            aperture=self.aperture,
            note=self.note,
        )


COL_PURPOSE, COL_GRADE, COL_SECONDS, COL_APERTURE, COL_NOTE = range(5)


class ExposureModel(QAbstractTableModel):
    edited = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[ExposureRow] = []
        self.headers = [_tr("Purpose"), _tr("Filter"), _tr("Seconds"), _tr("Aperture"),
                        _tr("Note")]  # fmt: skip

    def set_rows(self, rows: list[ExposureRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.headers)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return str(section + 1)

    def flags(self, index: AnyIndex) -> Qt.ItemFlag:
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        r = self.rows[index.row()]
        c = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                label(r.purpose),
                _tr("no filter") if r.filter_grade == "none" else r.filter_grade,
                format_seconds(r.seconds),
                r.aperture,
                r.note,
            ][c]
        if role == Qt.ItemDataRole.EditRole:
            return [r.purpose.value, r.filter_grade, r.seconds, r.aperture, r.note][c]
        if role == Qt.ItemDataRole.TextAlignmentRole and c == COL_SECONDS:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def setData(self, index: AnyIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        r = self.rows[index.row()]
        c = index.column()
        if c == COL_PURPOSE:
            r.purpose = ExposurePurpose(value)
        elif c == COL_GRADE:
            r.filter_grade = str(value)
        elif c == COL_SECONDS:
            r.seconds = max(0.0, float(value))
        elif c == COL_APERTURE:
            r.aperture = str(value).strip()
        else:
            r.note = str(value)
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True

    def add(self, row: ExposureRow, at: int | None = None) -> int:
        at = len(self.rows) if at is None else at
        self.beginInsertRows(QModelIndex(), at, at)
        self.rows.insert(at, row)
        self.endInsertRows()
        self.edited.emit()
        return at

    def remove(self, at: int) -> None:
        if 0 <= at < len(self.rows):
            self.beginRemoveRows(QModelIndex(), at, at)
            del self.rows[at]
            self.endRemoveRows()
            self.edited.emit()

    def move(self, at: int, delta: int) -> int:
        to = at + delta
        if not (0 <= at < len(self.rows) and 0 <= to < len(self.rows)):
            return at
        self.beginResetModel()
        self.rows[at], self.rows[to] = self.rows[to], self.rows[at]
        self.endResetModel()
        self.edited.emit()
        return to


class ExposureDelegate(QStyledItemDelegate):
    def createEditor(  # noqa: N802
        self, parent: QWidget, option: QStyleOptionViewItem, index: AnyIndex
    ) -> QWidget:
        c = index.column()
        if c == COL_PURPOSE:
            combo = QComboBox(parent)
            for p in ExposurePurpose:
                combo.addItem(label(p), p.value)
            return combo
        if c == COL_GRADE:
            combo = QComboBox(parent)
            for g in FILTER_GRADES:
                combo.addItem(_tr("no filter") if g == "none" else g, g)
            return combo
        if c == COL_SECONDS:
            spin = QDoubleSpinBox(parent)
            spin.setRange(0.0, 9999.0)
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setSuffix(" s")
            return spin
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor: QWidget, index: AnyIndex) -> None:  # noqa: N802
        value = index.data(Qt.ItemDataRole.EditRole)
        if isinstance(editor, QComboBox):
            editor.setCurrentIndex(max(0, editor.findData(value)))
        elif isinstance(editor, QDoubleSpinBox):
            editor.setValue(float(value or 0))
            editor.selectAll()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor: QWidget, model: Any, index: AnyIndex) -> None:  # noqa: N802
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentData())
        elif isinstance(editor, QDoubleSpinBox):
            editor.interpretText()
            model.setData(index, editor.value())
        else:
            super().setModelData(editor, model, index)


class ExposureTable(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = ExposureModel(self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(ExposureDelegate(self.view))
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.AllEditTriggers
            & ~QAbstractItemView.EditTrigger.CurrentChanged
        )
        self.view.setTabKeyNavigation(False)
        self.view.setMinimumHeight(130)
        self.view.setMaximumHeight(200)
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        h.setStretchLastSection(True)
        for col, w in ((COL_PURPOSE, 80), (COL_GRADE, 70), (COL_SECONDS, 75), (COL_APERTURE, 70)):
            self.view.setColumnWidth(col, w)
        self.view.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 10)

        def btn(text: str, tip: str) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tip)
            return b

        self.add_btn = btn(_tr("+ Exposure"), _tr("Add a base / soft / hard exposure"))
        self.burn_btn = btn(_tr("+ Burn"), _tr("Add a burn-in"))
        self.dodge_btn = btn(_tr("+ Dodge"), _tr("Add a dodge (held back during the base)"))
        self.remove_btn = btn(_tr("Remove"), _tr("Remove the selected row"))
        self.up_btn = btn("↑", _tr("Move up"))
        self.down_btn = btn("↓", _tr("Move down"))
        for b in (self.up_btn, self.down_btn):
            b.setMaximumWidth(34)
        self.add_btn.clicked.connect(lambda: self._add(ExposurePurpose.BASE))
        self.burn_btn.clicked.connect(lambda: self._add(ExposurePurpose.BURN))
        self.dodge_btn.clicked.connect(lambda: self._add(ExposurePurpose.DODGE))
        self.remove_btn.clicked.connect(self._remove)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.total = QLabel()
        bar = QHBoxLayout()
        for b in (self.add_btn, self.burn_btn, self.dodge_btn, self.remove_btn, self.up_btn,
                  self.down_btn):  # fmt: skip
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.total)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.view)
        v.addLayout(bar)
        self.model.edited.connect(self._edited)
        self.model.modelReset.connect(self._update_total)

    def rows(self) -> list[ExposureRow]:
        return self.model.rows

    def set_rows(self, rows: list[ExposureRow]) -> None:
        self.model.set_rows(rows)
        self._update_total()

    def _edited(self) -> None:
        self._update_total()
        self.changed.emit()

    def _update_total(self) -> None:
        total = sum(r.seconds for r in self.model.rows if r.purpose != ExposurePurpose.DODGE)
        self.total.setText(_tr("<b>Total exposure: {0}</b>").format(format_seconds(total)))

    def _current(self) -> int:
        idx = self.view.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _add(self, purpose: ExposurePurpose) -> None:
        last = self.model.rows[-1] if self.model.rows else None
        grade = last.filter_grade if last else "2"
        if purpose == ExposurePurpose.BASE and last and last.purpose == ExposurePurpose.SOFT:
            purpose, grade = ExposurePurpose.HARD, "5"
        at = self.model.add(ExposureRow(purpose=purpose, filter_grade=grade))
        self.view.setCurrentIndex(self.model.index(at, COL_SECONDS))
        self.view.edit(self.model.index(at, COL_SECONDS))

    def _remove(self) -> None:
        self.model.remove(self._current())

    def _move(self, delta: int) -> None:
        at = self._current()
        if at >= 0:
            to = self.model.move(at, delta)
            self.view.selectRow(to)


# --------------------------------------------------------------------------- print form


class PrintForm(EditorForm):
    openRoll = Signal(int)  # noqa: N815

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self.fixed_roll: Roll | None = None
        self.prefill_note = QLabel()
        self.prefill_note.setProperty("role", "prefill-note")
        self.prefill_note.setWordWrap(True)
        self.prefill_note.hide()
        self.layout().insertWidget(1, self.prefill_note)  # type: ignore[union-attr]
        self._original_image: str | None = None
        self._prefill_source: Print | None = None
        self.exposures.changed.connect(self._mark_dirty)
        self.image.changed.connect(self._mark_dirty)

    def build(self, form: FormBuilder) -> None:
        unit = self.ctx.settings.temperature_unit
        self.roll = RefCombo(allow_none=False)
        self.roll.currentIndexChanged.connect(self._roll_changed)
        self.open_roll = QPushButton(self.tr("Open roll"))
        self.open_roll.setToolTip(self.tr("Show this print's roll in the Rolls view"))
        self.open_roll.clicked.connect(self._open_roll)
        self.frame = QLineEdit()
        self.frame.setMaximumWidth(80)
        self.frame.setPlaceholderText("12A")
        self.title = QLineEdit()
        self.date = OptionalDateEdit()
        self.paper = RefCombo()
        self.paper_size = QComboBox()
        self.paper_size.setEditable(True)
        self.paper_size.addItems(list(PAPER_SIZES))
        self.paper_size.setToolTip(self.tr("Pick a preset or type a custom size"))
        self.enlarger = QLineEdit()
        self.lens = QLineEdit()
        self.aperture = QLineEdit()
        self.aperture.setMaximumWidth(80)
        self.aperture.setPlaceholderText("f/8")
        self.head = OptionalDoubleSpin(0, 500, 1)
        self.method = EnumCombo(ContrastMethod)
        self.method.currentIndexChanged.connect(self._method_changed)
        self.exposures = ExposureTable()
        self.developer = RefCombo()
        self.developer.currentIndexChanged.connect(self._developer_changed)
        self.dev_dilution = QLineEdit()
        self.dev_dilution.setMaximumWidth(110)
        self.dev_chips = ChipRow(self.dev_dilution)
        self.dev_time = DurationEdit()
        self.dev_temp = TemperatureSpin(unit)
        self.stop = RefCombo()
        self.stop_time = DurationEdit()
        self.fixer = RefCombo()
        self.fixer.currentIndexChanged.connect(self._fixer_changed)
        self.fixer_dilution = QLineEdit()
        self.fixer_dilution.setMaximumWidth(110)
        self.fixer_chips = ChipRow(self.fixer_dilution)
        self.fix_time = DurationEdit()
        self.wash_time = DurationEdit()
        self.toning = QLineEdit()
        self.toning.setPlaceholderText(self.tr("e.g. Selenium 1+9, 3 min"))
        self.final = QCheckBox(self.tr("Final print (not a work print)"))
        self.rating = RatingCombo()
        self.image = ImageField(160)
        self.notes = notes_edit()

        self.f_roll = form.add(self.tr("Roll"), row(self.roll, self.open_roll), self.roll)
        form.add(self.tr("Frame"), row(self.frame, self.tr("Title"), self.title, stretch=False),
                 self.frame, self.title)  # fmt: skip
        form.add(self.tr("Date printed"), self.date)
        form.section(self.tr("Paper & enlarger"))
        form.add(self.tr("Paper"), row(self.paper, self.tr("Size"), self.paper_size, stretch=False),
                 self.paper, self.paper_size)  # fmt: skip
        form.add(self.tr("Enlarger"), row(self.enlarger, self.tr("Lens"), self.lens,
                                          stretch=False), self.enlarger, self.lens)  # fmt: skip
        self.head_label = QLabel()
        form.add(self.tr("Aperture"), row(self.aperture, self.head_label, self.head),
                 self.aperture, self.head)  # fmt: skip
        form.section(self.tr("Exposure"))
        form.add(self.tr("Contrast"), self.method)
        self.f_exp = form.add(self.tr("Exposures"), self.exposures, self.exposures.view)
        form.section(self.tr("Processing"))
        form.add(self.tr("Developer"), self.developer)
        form.add(self.tr("Dilution"), row(self.dev_dilution, self.dev_chips), self.dev_dilution)
        self.f_dev_time = form.add(self.tr("Dev time / temp"),
                                   row(self.dev_time, self.dev_temp), self.dev_time,
                                   self.dev_temp)  # fmt: skip
        self.f_stop = form.add(self.tr("Stop"), row(self.stop, self.tr("time"), self.stop_time),
                               self.stop, self.stop_time)  # fmt: skip
        form.add(self.tr("Fixer"), row(self.fixer, self.fixer_dilution, self.fixer_chips),
                 self.fixer, self.fixer_dilution)  # fmt: skip
        self.f_fix = form.add(self.tr("Fix time"), self.fix_time)
        self.f_wash = form.add(self.tr("Wash"), self.wash_time)
        form.add(self.tr("Toning"), self.toning)
        form.section(self.tr("Result"))
        form.add("", self.final)
        form.add(self.tr("Rating"), self.rating)
        form.add(self.tr("Image"), self.image, self.image.choose)
        form.add(self.tr("Notes"), self.notes)
        self._durations = {
            self.f_dev_time: self.dev_time,
            self.f_stop: self.stop_time,
            self.f_fix: self.fix_time,
            self.f_wash: self.wash_time,
        }

    def extra_change_widgets(self) -> list[QWidget]:
        return [self.dev_chips, self.fixer_chips]

    # -- reference data -----------------------------------------------------------

    def _reload_refs(self, p: Print) -> None:
        s = self.ctx.session
        rolls = s.scalars(select(Roll).order_by(Roll.code.desc())).all()
        self.roll.set_items(((r.id, f"{r.code}  {r.title}".strip()) for r in rolls), keep=False)
        papers = [x for x in cat.papers(s) if not x.discontinued or x.id == p.paper_id]
        self.paper.set_items(((x.id, x.display_name) for x in papers), keep=False)
        self.developer.set_items(
            chemical_items(cat.chemicals(s, [ChemicalKind.PAPER_DEVELOPER]), [p.developer_id]),
            keep=False,
        )
        self.stop.set_items(
            chemical_items(cat.chemicals(s, [ChemicalKind.STOP_BATH]), [p.stop_chemical_id]),
            keep=False,
        )
        self.fixer.set_items(
            chemical_items(cat.chemicals(s, [ChemicalKind.FIXER]), [p.fixer_id]), keep=False
        )
        unit = self.ctx.settings.length_unit
        self.head_label.setText(self.tr("Head height ({0})").format(unit))
        self.dev_temp.set_unit(self.ctx.settings.temperature_unit)

    def _developer_changed(self) -> None:
        chem = self.ctx.session.get(Chemical, self.developer.current_id() or -1)
        self.dev_chips.set_chips(dilution_chips(chem) if chem else [])

    def _fixer_changed(self) -> None:
        chem = self.ctx.session.get(Chemical, self.fixer.current_id() or -1)
        self.fixer_chips.set_chips(chem.dilution_list if chem else [])

    def _roll_changed(self) -> None:
        self.open_roll.setEnabled(self.roll.current_id() is not None)

    def _open_roll(self) -> None:
        rid = self.roll.current_id()
        if rid is not None:
            self.openRoll.emit(rid)

    def _method_changed(self) -> None:
        if self._loading:
            return
        rows = self.exposures.rows()
        untouched = all(r.seconds == 0 for r in rows)
        if untouched:
            method = self.method.value()
            self.exposures.set_rows([ExposureRow.from_model(e) for e in default_exposures(method)])
            self._mark_dirty()

    # -- EditorForm -----------------------------------------------------------------

    def new_object(self) -> Print:
        p, src = new_print_for(self.ctx.session, self.fixed_roll)
        self._prefill_source = src
        return p

    def heading_for(self, obj: Print, is_new: bool) -> str:
        if is_new:
            return self.tr("New print")
        frame = obj.frame or "?"
        code = obj.roll.code if obj.roll else ""
        return self.tr("Print {0} · frame {1}").format(code, frame) + (
            f" — {obj.title}" if obj.title else ""
        )

    def load_new(self, roll: Roll | None) -> None:
        self.fixed_roll = roll
        self._prefill_source = None
        self.load(None)
        src = self._prefill_source
        if src is not None:
            self.prefill_note.setText(
                self.tr(
                    "Paper, enlarger and chemistry copied from your last print ({0}, frame {1})."
                ).format(src.roll.code, src.frame or "?")
            )
        self.prefill_note.setVisible(src is not None)

    def load_print(self, p: Print, note: str = "") -> None:
        self.load(p)
        self.prefill_note.setText(note)
        self.prefill_note.setVisible(bool(note))

    def populate(self, obj: Print) -> None:
        self.discard_imports()  # files picked during an abandoned edit
        self._reload_refs(obj)
        unit = self.ctx.settings.length_unit
        self.roll.set_current_id(obj.roll_id)
        self._roll_changed()
        self.frame.setText(obj.frame or "")
        self.title.setText(obj.title or "")
        self.date.set_value(obj.date_printed)
        self.paper.set_current_id(obj.paper_id)
        self.paper_size.setCurrentText(obj.paper_size or "")
        self.enlarger.setText(obj.enlarger or "")
        self.lens.setText(obj.enlarging_lens or "")
        self.aperture.setText(obj.aperture or "")
        self.head.set_value(to_display_length(obj.head_height_cm, unit))
        self.method.set_value(obj.contrast_method)
        self.exposures.set_rows([ExposureRow.from_model(e) for e in obj.exposures])
        self.developer.set_current_id(obj.developer_id)
        self._developer_changed()
        self.dev_dilution.setText(obj.dev_dilution or "")
        self.dev_time.set_value(obj.dev_time_s)
        self.dev_temp.set_celsius(obj.dev_temperature_c)
        self.stop.set_current_id(obj.stop_chemical_id)
        self.stop_time.set_value(obj.stop_time_s)
        self.fixer.set_current_id(obj.fixer_id)
        self._fixer_changed()
        self.fixer_dilution.setText(obj.fixer_dilution or "")
        self.fix_time.set_value(obj.fix_time_s)
        self.wash_time.set_value(obj.wash_time_s)
        self.toning.setText(obj.toning or "")
        self.final.setChecked(bool(obj.is_final))
        self.rating.set_value(obj.rating)
        self.image.set_name(obj.image)
        self._original_image = obj.image if obj.id is not None else None
        self.notes.setPlainText(obj.notes or "")
        self.roll.setEnabled(obj.id is None and self.fixed_roll is None)
        for f in (self.f_roll, self.f_exp, *self._durations):
            f.set_error(None)

    def validate(self) -> bool:
        ok = self.f_roll.set_error(None if self.roll.current_id() else self.tr("Choose the roll."))
        for field, edit in self._durations.items():
            ok = field.set_error(None if edit.is_valid() else self.tr("Use m:ss, e.g. 1:30")) and ok
        main = [
            r for r in self.exposures.rows()
            if r.purpose in (ExposurePurpose.BASE, ExposurePurpose.SOFT, ExposurePurpose.HARD)
        ]  # fmt: skip
        if not main or not any(r.seconds > 0 for r in main):
            ok = self.f_exp.set_error(self.tr("Enter at least one exposure time.")) and ok
        elif self.method.value() == ContrastMethod.SPLIT_GRADE and len(main) < 2:
            ok = (
                self.f_exp.set_error(self.tr("Split grade needs a soft and a hard exposure."))
                and ok
            )
        else:
            self.f_exp.set_error(None)
        return ok

    def apply(self, obj: Print) -> None:
        s = self.ctx.session
        unit = self.ctx.settings.length_unit
        roll = s.get(Roll, self.roll.current_id())
        assert roll is not None
        obj.roll = roll
        obj.frame = self.frame.text().strip()
        obj.title = self.title.text().strip()
        obj.date_printed = self.date.value()
        pid = self.paper.current_id()
        obj.paper = s.get(Paper, pid) if pid else None
        obj.paper_size = self.paper_size.currentText().strip()
        obj.enlarger = self.enlarger.text().strip()
        obj.enlarging_lens = self.lens.text().strip()
        obj.aperture = self.aperture.text().strip()
        obj.head_height_cm = from_display_length(self.head.value_or_none(), unit)
        obj.contrast_method = self.method.value()
        obj.exposures = [r.to_model(i) for i, r in enumerate(self.exposures.rows())]
        obj.developer_id = self.developer.current_id()
        obj.dev_dilution = self.dev_dilution.text().strip()
        obj.dev_time_s = self.dev_time.value()
        obj.dev_temperature_c = self.dev_temp.celsius()
        obj.stop_chemical_id = self.stop.current_id()
        obj.stop_time_s = self.stop_time.value()
        obj.fixer_id = self.fixer.current_id()
        obj.fixer_dilution = self.fixer_dilution.text().strip()
        obj.fix_time_s = self.fix_time.value()
        obj.wash_time_s = self.wash_time.value()
        obj.toning = self.toning.text().strip()
        obj.is_final = self.final.isChecked()
        obj.rating = self.rating.value()
        obj.image = self.image.name()
        obj.notes = self.notes.toPlainText()

    def after_save(self, obj: Any, is_new: bool) -> None:
        # Drop files replaced or removed during this edit.
        stale = [self._original_image, *self.image.imported]
        delete_unreferenced(self.ctx.session, stale)
        forget_thumbnail(self._original_image)
        self._original_image = obj.image
        self.image.imported = []
        self.prefill_note.hide()

    def discard_imports(self) -> None:
        delete_unreferenced(self.ctx.session, self.image.imported)
        self.image.imported = []

    def cancel(self) -> None:
        self.discard_imports()
        super().cancel()


class PrintDialog(QDialog):
    """Modal editor for one print (used from the roll's Prints tab)."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Print"))
        self.form = PrintForm(ctx)
        self.form.open_roll.hide()  # already shown from the roll
        self.form.saved.connect(lambda _: self.accept())
        self.form.cancelled.connect(self.reject)
        v = QVBoxLayout(self)
        v.addWidget(self.form)
        self.resize(760, 860)

    def reject(self) -> None:
        if self.form.dirty and not self.form.maybe_discard():
            return
        self.form.discard_imports()
        super().reject()
