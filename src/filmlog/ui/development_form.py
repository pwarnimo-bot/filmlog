# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Development form with pre-fill note and a "past results" recipe panel."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from filmlog.db.enums import DEFAULT_DILUTIONS, ChemicalKind, RollStatus
from filmlog.db.models import Chemical, Development, Roll
from filmlog.services import catalogue as cat
from filmlog.services.development import Prefill, new_development_for, past_results
from filmlog.services.timefmt import format_duration
from filmlog.services.units import format_temp
from filmlog.ui.catalogue_view import notes_edit
from filmlog.ui.context import AppContext
from filmlog.ui.editor import EditorForm
from filmlog.ui.table_model import Column, ObjectTable
from filmlog.ui.widgets import (
    ChipRow,
    DurationEdit,
    FormBuilder,
    ListCompleter,
    OptionalDateEdit,
    RatingCombo,
    RefCombo,
    TemperatureSpin,
    push_pull_badge,
    row,
    set_completions,
    stars,
)

WASH_METHODS = (
    "Ilford method 5/10/20 inversions",
    "Running water",
    "Running water 10 min",
    "Running water 20 min",
)


def _tr(text: str) -> str:
    return QCoreApplication.translate("Development", text)


def chemical_items(
    chems: Sequence[Chemical], current_ids: Sequence[int | None] = ()
) -> list[tuple[int, str]]:
    """(id, name) pairs, hiding discontinued chemicals unless currently selected."""
    keep = {i for i in current_ids if i is not None}
    return [(c.id, c.display_name) for c in chems if not c.discontinued or c.id in keep]


def dilution_chips(chem: Chemical | None) -> list[str]:
    own = chem.dilution_list if chem is not None else []
    return own or list(DEFAULT_DILUTIONS)


class DevelopmentForm(EditorForm):
    useRecipe = Signal(object)  # noqa: N815

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(ctx, parent)
        self.roll: Roll | None = None
        self.prefill_note = QLabel()
        self.prefill_note.setProperty("role", "prefill-note")
        self.prefill_note.setWordWrap(True)
        self.prefill_note.hide()
        self.layout().insertWidget(1, self.prefill_note)  # type: ignore[union-attr]

    # -- build -----------------------------------------------------------------

    def build(self, form: FormBuilder) -> None:
        unit = self.ctx.settings.temperature_unit
        self.date = OptionalDateEdit()
        self.developer = RefCombo(allow_none=False)
        self.dilution = QLineEdit()
        self.dilution.setMaximumWidth(140)
        self.dilution_chips = ChipRow(self.dilution)
        self.temp = TemperatureSpin(unit)
        self.dev_time = DurationEdit()
        self.agitation_preset = QComboBox()
        self.agitation = QPlainTextEdit()
        self.agitation.setTabChangesFocus(True)
        self.agitation.setFixedHeight(54)
        self.presoak = DurationEdit()
        self.stop = RefCombo()
        self.stop_time = DurationEdit()
        self.rinse_time = DurationEdit()
        self.fixer = RefCombo()
        self.fixer_dilution = QLineEdit()
        self.fixer_dilution.setMaximumWidth(140)
        self.fixer_chips = ChipRow(self.fixer_dilution)
        self.fix_time = DurationEdit()
        self.wash_time = DurationEdit()
        self.wash_method = QLineEdit()
        set_completions(self.wash_method, WASH_METHODS)
        self.wetting = RefCombo()
        self.wetting_time = DurationEdit()
        self.tank = QLineEdit()
        self.tank.setPlaceholderText(self.tr("e.g. Paterson Super System 4, 2-reel"))
        self.with_rolls = QLineEdit()
        self.with_rolls.setPlaceholderText(self.tr("Roll codes, comma-separated"))
        self.with_completer = ListCompleter([], self.with_rolls)
        self.rating = RatingCombo()
        self.notes = notes_edit()

        self.agitation_preset.activated.connect(self._preset_picked)
        self.developer.currentIndexChanged.connect(self._developer_changed)
        self.fixer.currentIndexChanged.connect(self._fixer_changed)
        self.developer.currentIndexChanged.connect(self._emit_recipe_key)
        self.dilution.textChanged.connect(self._emit_recipe_key)

        form.add(self.tr("Date developed"), self.date)
        form.section(self.tr("Developer"))
        self.f_dev = form.add(self.tr("Developer"), self.developer)
        form.add(self.tr("Dilution"), row(self.dilution, self.dilution_chips), self.dilution)
        form.add(self.tr("Temperature"), self.temp)
        self.f_time = form.add(self.tr("Development time"), self.dev_time)
        form.add(
            self.tr("Agitation"),
            self._vbox(self.agitation_preset, self.agitation),
            self.agitation_preset,
            self.agitation,
        )
        self.f_presoak = form.add(self.tr("Pre-soak"), self.presoak)
        form.section(self.tr("Stop, fix, wash"))
        form.add(self.tr("Stop bath"), row(self.stop, self.tr("time"), self.stop_time),
                 self.stop, self.stop_time)  # fmt: skip
        self.f_rinse = form.add(self.tr("Rinse"), self.rinse_time)
        form.add(self.tr("Fixer"), self.fixer)
        form.add(self.tr("Fixer dilution"), row(self.fixer_dilution, self.fixer_chips),
                 self.fixer_dilution)  # fmt: skip
        self.f_fix = form.add(self.tr("Fix time"), self.fix_time)
        form.add(self.tr("Wash"), row(self.wash_time, self.wash_method, stretch=False),
                 self.wash_time, self.wash_method)  # fmt: skip
        form.add(self.tr("Wetting agent"), row(self.wetting, self.tr("time"), self.wetting_time),
                 self.wetting, self.wetting_time)  # fmt: skip
        form.section(self.tr("Other"))
        form.add(self.tr("Tank"), self.tank)
        self.f_with = form.add(self.tr("Developed with"), self.with_rolls)
        form.add(self.tr("Negatives"), self.rating)
        form.add(self.tr("Notes"), self.notes)
        self._durations = {
            self.f_time: self.dev_time,
            self.f_presoak: self.presoak,
            self.f_rinse: self.rinse_time,
            self.f_fix: self.fix_time,
        }

    @staticmethod
    def _vbox(*widgets: QWidget) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            v.addWidget(w)
        return v

    def extra_change_widgets(self) -> list[QWidget]:
        return [self.dilution_chips, self.fixer_chips]

    # -- reference data -------------------------------------------------------

    def _reload_refs(self, dev: Development) -> None:
        s = self.ctx.session
        self.developer.set_items(
            chemical_items(cat.chemicals(s, [ChemicalKind.FILM_DEVELOPER]), [dev.developer_id]),
            keep=False,
        )
        self.stop.set_items(
            chemical_items(cat.chemicals(s, [ChemicalKind.STOP_BATH]), [dev.stop_chemical_id]),
            keep=False,
        )
        self.fixer.set_items(
            chemical_items(cat.chemicals(s, [ChemicalKind.FIXER]), [dev.fixer_id]), keep=False
        )
        self.wetting.set_items(
            chemical_items(cat.chemicals(s, [ChemicalKind.WETTING_AGENT]), [dev.wetting_agent_id]),
            keep=False,
        )
        self.agitation_preset.clear()
        self.agitation_preset.addItem(self.tr("Pick a preset…"), None)
        for p in cat.agitation_presets(s):
            self.agitation_preset.addItem(p.name, p.text)
        codes = s.scalars(select(Roll.code).order_by(Roll.code.desc())).all()
        own = self.roll.code if self.roll else None
        self.with_completer.set_words([c for c in codes if c != own])
        self.temp.set_unit(self.ctx.settings.temperature_unit)

    def _preset_picked(self, index: int) -> None:
        text = self.agitation_preset.itemData(index)
        if text is not None:
            self.agitation.setPlainText(text)
            self.agitation.setFocus()
            self.agitation.moveCursor(self.agitation.textCursor().MoveOperation.End)
        self.agitation_preset.setCurrentIndex(0)

    def _developer_changed(self) -> None:
        chem = self.ctx.session.get(Chemical, self.developer.current_id() or -1)
        self.dilution_chips.set_chips(dilution_chips(chem))

    def _fixer_changed(self) -> None:
        chem = self.ctx.session.get(Chemical, self.fixer.current_id() or -1)
        self.fixer_chips.set_chips(chem.dilution_list if chem else [])

    def _emit_recipe_key(self) -> None:
        if not self._loading:
            self.useRecipe.emit(None)

    # -- EditorForm -----------------------------------------------------------

    def load_for_roll(self, roll: Roll) -> Prefill | None:
        """Show the roll's development, or a new pre-filled one. Returns the pre-fill."""
        self.roll = roll
        pre: Prefill | None = None
        if roll.development is not None:
            self.load(roll.development)
        else:
            dev, pre = new_development_for(self.ctx.session, roll)
            self.load(dev)
        if pre is not None:
            src = pre.source.roll
            self.prefill_note.setText(
                self.tr("Pre-filled from roll {0} — edit as needed.").format(src.code)
                + "  "
                + {
                    "same_film_ei": self.tr("(same film and EI)"),
                    "same_film": self.tr("(same film, different EI)"),
                    "last": self.tr("(most recent development)"),
                }[pre.reason]
            )
        self.prefill_note.setVisible(pre is not None)
        return pre

    def new_object(self) -> Development:
        return Development(temperature_c=20.0)

    def heading_for(self, obj: Development, is_new: bool) -> str:
        code = self.roll.code if self.roll else ""
        return (
            self.tr("Develop roll {0}").format(code)
            if is_new
            else self.tr("Development of {0}").format(code)
        )

    def populate(self, obj: Development) -> None:
        self._reload_refs(obj)
        self.date.set_value(obj.date_developed)
        self.developer.set_current_id(obj.developer_id)
        self._developer_changed()
        self.dilution.setText(obj.dilution or "")
        self.temp.set_celsius(obj.temperature_c)
        self.dev_time.set_value(obj.dev_time_s)
        self.agitation.setPlainText(obj.agitation or "")
        self.presoak.set_value(obj.presoak_s)
        self.stop.set_current_id(obj.stop_chemical_id)
        self.stop_time.set_value(obj.stop_time_s)
        self.rinse_time.set_value(obj.rinse_time_s)
        self.fixer.set_current_id(obj.fixer_id)
        self._fixer_changed()
        self.fixer_dilution.setText(obj.fixer_dilution or "")
        self.fix_time.set_value(obj.fix_time_s)
        self.wash_time.set_value(obj.wash_time_s)
        self.wash_method.setText(obj.wash_method or "")
        self.wetting.set_current_id(obj.wetting_agent_id)
        self.wetting_time.set_value(obj.wetting_time_s)
        self.tank.setText(obj.tank or "")
        with_rolls = obj.developed_with_rolls if obj.id is not None else []
        self.with_rolls.setText(", ".join(r.code for r in with_rolls))
        self.rating.set_value(obj.result_rating)
        self.notes.setPlainText(obj.notes or "")
        for f in (self.f_dev, self.f_time, self.f_with, *self._durations):
            f.set_error(None)

    def _with_roll_objects(self) -> tuple[list[Roll], list[str]]:
        codes = [c.strip() for c in self.with_rolls.text().split(",") if c.strip()]
        found: list[Roll] = []
        missing: list[str] = []
        for code in codes:
            r = self.ctx.session.scalar(select(Roll).where(Roll.code == code))
            if r is None or r is self.roll:
                missing.append(code)
            elif r not in found:
                found.append(r)
        return found, missing

    def validate(self) -> bool:
        ok = self.f_dev.set_error(
            None if self.developer.current_id() else self.tr("Choose the developer.")
        )
        for field, edit in self._durations.items():
            if not edit.is_valid():
                ok = field.set_error(self.tr("Use m:ss, e.g. 8:30")) and ok
            else:
                field.set_error(None)
        if self.dev_time.is_valid() and not self.dev_time.value():
            ok = self.f_time.set_error(self.tr("Development time is required.")) and ok
        for e in (self.stop_time, self.wash_time, self.wetting_time):
            if not e.is_valid():
                ok = False
                e.setFocus()
        _, missing = self._with_roll_objects()
        ok = (
            self.f_with.set_error(
                self.tr("Unknown roll code(s): {0}").format(", ".join(missing)) if missing else None
            )
            and ok
        )
        return ok

    def apply(self, obj: Development) -> None:
        assert self.roll is not None
        obj.date_developed = self.date.value()
        obj.developer_id = self.developer.current_id()
        obj.dilution = self.dilution.text().strip()
        obj.temperature_c = self.temp.celsius()
        obj.dev_time_s = self.dev_time.value() or 0
        obj.agitation = self.agitation.toPlainText().strip()
        obj.presoak_s = self.presoak.value()
        obj.stop_chemical_id = self.stop.current_id()
        obj.stop_time_s = self.stop_time.value()
        obj.rinse_time_s = self.rinse_time.value()
        obj.fixer_id = self.fixer.current_id()
        obj.fixer_dilution = self.fixer_dilution.text().strip()
        obj.fix_time_s = self.fix_time.value()
        obj.wash_time_s = self.wash_time.value()
        obj.wash_method = self.wash_method.text().strip()
        obj.wetting_agent_id = self.wetting.current_id()
        obj.wetting_time_s = self.wetting_time.value()
        obj.tank = self.tank.text().strip()
        obj.developed_with_rolls = self._with_roll_objects()[0]
        obj.result_rating = self.rating.value()
        obj.notes = self.notes.toPlainText()
        # Linking marks the roll developed (only developed rolls have a development).
        self.roll.development = obj
        self.roll.status = RollStatus.DEVELOPED

    def after_save(self, obj: Any, is_new: bool) -> None:
        self.prefill_note.hide()

    def cancel(self) -> None:
        if self.obj is None:
            return
        if self.is_new():
            # Abandon the unsaved development; the roll stays as it was.
            self.prefill_note.hide()
            self.clear()
            self.cancelled.emit()
            return
        super().cancel()

    def apply_recipe(self, dev: Development) -> None:
        """Copy time, temperature, dilution and agitation from a past result."""
        self.dilution.setText(dev.dilution or "")
        self.temp.set_celsius(dev.temperature_c)
        self.dev_time.set_value(dev.dev_time_s)
        self.agitation.setPlainText(dev.agitation or "")
        self._mark_dirty()


class PastResultsPanel(QWidget):
    """Previous developments with the same film + developer (+ dilution)."""

    def __init__(self, ctx: AppContext, form: DevelopmentForm) -> None:
        super().__init__()
        self.ctx = ctx
        self.form = form
        unit = lambda: ctx.settings.temperature_unit  # noqa: E731
        self.table = ObjectTable(
            "past_results",
            [
                Column(_tr("Roll"), lambda d: d.roll.code, width=80),
                Column(_tr("Date"), lambda d: d.date_developed, width=85),
                Column(
                    _tr("EI"),
                    lambda d: d.roll.shot_iso,
                    align_right=True,
                    width=60,
                    chip=lambda d: (
                        push_pull_badge(d.roll.push_pull_stops)
                        if round(d.roll.push_pull_stops * 3)
                        else None
                    ),
                ),  # fmt: skip
                Column(_tr("Dil."), lambda d: d.dilution, width=55),
                Column(
                    _tr("Time"),
                    lambda d: format_duration(d.dev_time_s),
                    sort=lambda d: d.dev_time_s,
                    align_right=True,
                    width=55,
                ),  # fmt: skip
                Column(_tr("Temp"), lambda d: format_temp(d.temperature_c, unit()), width=60),
                Column(
                    _tr("Rating"),
                    lambda d: stars(d.result_rating),
                    sort=lambda d: d.result_rating or 0,
                    width=75,
                ),  # fmt: skip
                Column(
                    _tr("Agitation"),
                    lambda d: d.agitation,
                    width=200,
                    tooltip=lambda d: d.agitation,
                ),  # fmt: skip
            ],
            ctx.settings,
        )
        self.table.doubleClicked.connect(lambda _: self._use())
        self.same_dilution = QCheckBox(_tr("Same dilution only"))
        self.same_dilution.setChecked(True)
        self.same_dilution.toggled.connect(self.refresh)
        self.use_button = QPushButton(_tr("Use selected"))
        self.use_button.setToolTip(_tr("Copy dilution, time, temperature and agitation"))
        self.use_button.clicked.connect(self._use)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        disclaimer = QLabel(_tr("Your own past results. Published times are starting points only."))
        disclaimer.setWordWrap(True)
        disclaimer.setEnabled(False)
        head = QHBoxLayout()
        head.addWidget(self.same_dilution)
        head.addStretch(1)
        head.addWidget(self.use_button)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.caption)
        v.addLayout(head)
        v.addWidget(self.table, 1)
        v.addWidget(disclaimer)

    def refresh(self) -> None:
        roll = self.form.roll
        if roll is None or self.form.obj is None:
            self.table.set_items([])
            self.caption.setText("")
            return
        dev_id = self.form.developer.current_id()
        dil = self.form.dilution.text().strip() if self.same_dilution.isChecked() else None
        rows = past_results(
            self.ctx.session, roll.film_stock_id, dev_id, dil, exclude_roll_id=roll.id
        )
        chem = self.ctx.session.get(Chemical, dev_id) if dev_id else None
        what = roll.film_stock.display_name + (f" · {chem.display_name}" if chem else "")
        if dil:
            what += f" {dil}"
        self.caption.setText(_tr("<b>Past results</b> — {0} ({1})").format(what, len(rows)))
        self.table.set_items(rows)

    def _use(self) -> None:
        dev = self.table.current_object()
        if dev is not None:
            self.form.apply_recipe(dev)


class DevelopmentTab(QWidget):
    """Development tab: the form plus a toggleable past-results side panel."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.form = DevelopmentForm(ctx)
        self.past = PastResultsPanel(ctx, self.form)
        self.form.useRecipe.connect(lambda _: self._refresh_past())
        self.toggle_past = QPushButton(_tr("Show past results"))
        self.toggle_past.setCheckable(True)
        self.toggle_past.toggled.connect(self._toggle)
        self.delete_button = QPushButton(_tr("Delete development"))
        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.form)
        split.addWidget(self.past)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        self.past.hide()
        self.split = split

        bar = QHBoxLayout()
        bar.addWidget(self.toggle_past)
        bar.addStretch(1)
        bar.addWidget(self.delete_button)
        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(self.empty, 1)
        v.addWidget(split, 1)

    def _toggle(self, on: bool) -> None:
        self.past.setVisible(on)
        self.toggle_past.setText(_tr("Hide past results") if on else _tr("Show past results"))
        if on:
            self._refresh_past()

    def _refresh_past(self) -> None:
        if self.past.isVisible():
            self.past.refresh()

    def show_message(self, text: str) -> None:
        self.form.clear()
        self.empty.setText(text)
        self.empty.show()
        self.split.hide()
        self.toggle_past.setEnabled(False)
        self.delete_button.setEnabled(False)

    def show_form(self, roll: Roll) -> Prefill | None:
        pre = self.form.load_for_roll(roll)
        self.empty.hide()
        self.split.show()
        self.toggle_past.setEnabled(True)
        self.delete_button.setEnabled(not self.form.is_new())
        self._refresh_past()
        return pre
