# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalogue view: films, chemicals, papers, manufacturers, agitation presets."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import func, select

from filmlog.db.enums import (
    ChemicalForm,
    ChemicalKind,
    ContrastType,
    FilmType,
    PaperBase,
    PaperSurface,
    PaperTone,
)
from filmlog.db.models import AgitationPreset, Chemical, FilmStock, Manufacturer, Paper
from filmlog.services import catalogue as cat
from filmlog.ui.base_view import BaseView
from filmlog.ui.context import AppContext
from filmlog.ui.editor import EditorForm
from filmlog.ui.labels import label
from filmlog.ui.list_detail import ListDetailPanel
from filmlog.ui.table_model import Column
from filmlog.ui.widgets import EnumCombo, FormBuilder, RefCombo


def _tr(text: str) -> str:
    return QCoreApplication.translate("Catalogue", text)


def notes_edit() -> QPlainTextEdit:
    w = QPlainTextEdit()
    w.setTabChangesFocus(True)
    w.setFixedHeight(80)
    return w


def yes(v: bool) -> str:
    return "✓" if v else ""


class ManufacturerCombo(RefCombo):
    """Manufacturer picker with a "+ New manufacturer…" entry."""

    def __init__(self, ctx: AppContext, *, allow_none: bool = False) -> None:
        super().__init__(
            allow_none=allow_none, none_label="—", new_label=_tr("+ New manufacturer…")
        )
        self.ctx = ctx
        self.newRequested.connect(self._create)
        self.reload()

    def reload(self) -> None:
        self.set_items((m.id, m.name) for m in cat.manufacturers(self.ctx.session))

    def _create(self) -> None:
        name, ok = QInputDialog.getText(self, self.tr("New manufacturer"), self.tr("Name:"))
        name = name.strip()
        if not ok or not name:
            return
        s = self.ctx.session
        m = s.scalar(select(Manufacturer).where(func.lower(Manufacturer.name) == name.lower()))
        if m is None:
            m = Manufacturer(name=name)
            s.add(m)
            s.commit()
        self.reload()
        self.set_current_id(m.id)


# --------------------------------------------------------------------------- forms


class ManufacturerForm(EditorForm):
    def build(self, form: FormBuilder) -> None:
        self.name = QLineEdit()
        self.country = QLineEdit()
        self.notes = notes_edit()
        self.f_name = form.add(self.tr("Name"), self.name)
        form.add(self.tr("Country"), self.country)
        form.add(self.tr("Notes"), self.notes)

    def new_object(self) -> Manufacturer:
        return Manufacturer(name="")

    def heading_for(self, obj: Manufacturer, is_new: bool) -> str:
        return self.tr("New manufacturer") if is_new else obj.name

    def populate(self, obj: Manufacturer) -> None:
        self.name.setText(obj.name or "")
        self.country.setText(obj.country or "")
        self.notes.setPlainText(obj.notes or "")

    def validate(self) -> bool:
        name = self.name.text().strip()
        if not name:
            return self.f_name.set_error(self.tr("Name is required."))
        q = select(Manufacturer.id).where(func.lower(Manufacturer.name) == name.lower())
        if self.obj.id is not None:
            q = q.where(Manufacturer.id != self.obj.id)
        if self.ctx.session.scalar(q) is not None:
            return self.f_name.set_error(self.tr("A manufacturer with this name exists."))
        return self.f_name.set_error(None)

    def apply(self, obj: Manufacturer) -> None:
        obj.name = self.name.text().strip()
        obj.country = self.country.text().strip() or None
        obj.notes = self.notes.toPlainText()


class FilmStockForm(EditorForm):
    def build(self, form: FormBuilder) -> None:
        self.manufacturer = ManufacturerCombo(self.ctx)
        self.name = QLineEdit()
        self.name.setPlaceholderText(self.tr("e.g. FP4 Plus"))
        self.iso = QSpinBox()
        self.iso.setRange(1, 25600)
        self.iso.setValue(100)
        self.iso.setMaximumWidth(110)
        self.type = EnumCombo(FilmType)
        self.formats = QLineEdit()
        self.formats.setPlaceholderText("135, 120, sheet")
        self.aliases = QLineEdit()
        self.aliases.setPlaceholderText(self.tr("Other names this film is sold under"))
        self.discontinued = QCheckBox(self.tr("Discontinued"))
        self.notes = notes_edit()
        self.f_mfr = form.add(self.tr("Manufacturer"), self.manufacturer)
        self.f_name = form.add(self.tr("Name"), self.name)
        form.add(self.tr("Box ISO"), self.iso)
        form.add(self.tr("Type"), self.type)
        form.add(self.tr("Formats"), self.formats)
        form.add(self.tr("Aliases"), self.aliases)
        form.add("", self.discontinued)
        form.add(self.tr("Notes"), self.notes)

    def new_object(self) -> FilmStock:
        return FilmStock(name="", box_iso=100, type=FilmType.BW_NEGATIVE)

    def heading_for(self, obj: FilmStock, is_new: bool) -> str:
        return self.tr("New film stock") if is_new else obj.display_name

    def populate(self, obj: FilmStock) -> None:
        self.manufacturer.reload()
        self.manufacturer.set_current_id(obj.manufacturer_id)
        self.name.setText(obj.name or "")
        self.iso.setValue(obj.box_iso or 100)
        self.type.set_value(obj.type or FilmType.BW_NEGATIVE)
        self.formats.setText(obj.formats_available or "")
        self.aliases.setText(obj.aliases or "")
        self.discontinued.setChecked(bool(obj.discontinued))
        self.notes.setPlainText(obj.notes or "")

    def validate(self) -> bool:
        ok = self.f_mfr.set_error(
            None if self.manufacturer.current_id() else self.tr("Choose a manufacturer.")
        )
        name = self.name.text().strip()
        if not name:
            ok = self.f_name.set_error(self.tr("Name is required.")) and ok
        else:
            q = select(FilmStock.id).where(
                FilmStock.manufacturer_id == self.manufacturer.current_id(),
                func.lower(FilmStock.name) == name.lower(),
            )
            if self.obj.id is not None:
                q = q.where(FilmStock.id != self.obj.id)
            dup = self.ctx.session.scalar(q) is not None
            ok = self.f_name.set_error(self.tr("This film already exists.") if dup else None) and ok
        return ok

    def apply(self, obj: FilmStock) -> None:
        mfr = self.ctx.session.get(Manufacturer, self.manufacturer.current_id())
        assert mfr is not None
        obj.manufacturer = mfr
        obj.name = self.name.text().strip()
        obj.box_iso = self.iso.value()
        obj.type = self.type.value()
        obj.formats_available = self.formats.text().strip()
        obj.aliases = self.aliases.text().strip()
        obj.discontinued = self.discontinued.isChecked()
        obj.notes = self.notes.toPlainText()


class ChemicalForm_(EditorForm):  # noqa: N801 - avoid clash with enum name
    def build(self, form: FormBuilder) -> None:
        self.manufacturer = ManufacturerCombo(self.ctx, allow_none=True)
        self.name = QLineEdit()
        self.kind = EnumCombo(ChemicalKind)
        self.dilutions = QLineEdit()
        self.dilutions.setPlaceholderText(self.tr("e.g. stock; 1+1; 1+3"))
        self.form_ = EnumCombo(ChemicalForm)
        self.discontinued = QCheckBox(self.tr("Discontinued"))
        self.notes = notes_edit()
        form.add(self.tr("Manufacturer"), self.manufacturer)
        self.f_name = form.add(self.tr("Name"), self.name)
        form.add(self.tr("Kind"), self.kind)
        form.add(self.tr("Common dilutions"), self.dilutions)
        form.add(self.tr("Form"), self.form_)
        form.add("", self.discontinued)
        form.add(self.tr("Notes"), self.notes)

    def new_object(self) -> Chemical:
        return Chemical(name="", kind=ChemicalKind.FILM_DEVELOPER, form=ChemicalForm.LIQUID)

    def heading_for(self, obj: Chemical, is_new: bool) -> str:
        return self.tr("New chemical") if is_new else obj.display_name

    def populate(self, obj: Chemical) -> None:
        self.manufacturer.reload()
        self.manufacturer.set_current_id(obj.manufacturer_id)
        self.name.setText(obj.name or "")
        self.kind.set_value(obj.kind)
        self.dilutions.setText(obj.common_dilutions or "")
        self.form_.set_value(obj.form)
        self.discontinued.setChecked(bool(obj.discontinued))
        self.notes.setPlainText(obj.notes or "")
        builtin = bool(obj.is_builtin)
        for w in (self.manufacturer, self.name, self.kind):
            w.setEnabled(not builtin)

    def validate(self) -> bool:
        if not self.name.text().strip():
            return self.f_name.set_error(self.tr("Name is required."))
        return self.f_name.set_error(None)

    def apply(self, obj: Chemical) -> None:
        mid = self.manufacturer.current_id()
        obj.manufacturer = self.ctx.session.get(Manufacturer, mid) if mid else None
        obj.name = self.name.text().strip()
        obj.kind = self.kind.value()
        obj.common_dilutions = self.dilutions.text().strip()
        obj.form = self.form_.value()
        obj.discontinued = self.discontinued.isChecked()
        obj.notes = self.notes.toPlainText()


GRADES = ("00", "0", "1", "2", "3", "4", "5")


class PaperForm(EditorForm):
    def build(self, form: FormBuilder) -> None:
        self.manufacturer = ManufacturerCombo(self.ctx)
        self.name = QLineEdit()
        self.base = EnumCombo(PaperBase)
        self.contrast = EnumCombo(ContrastType)
        self.grade = QComboBox()
        self.grade.addItems(GRADES)
        self.surface = EnumCombo(PaperSurface)
        self.tone = EnumCombo(PaperTone)
        self.discontinued = QCheckBox(self.tr("Discontinued"))
        self.notes = notes_edit()
        self.contrast.currentIndexChanged.connect(self._sync_grade)
        self.f_mfr = form.add(self.tr("Manufacturer"), self.manufacturer)
        self.f_name = form.add(self.tr("Name"), self.name)
        form.add(self.tr("Base"), self.base)
        form.add(self.tr("Contrast"), self.contrast)
        self.f_grade = form.add(self.tr("Grade"), self.grade)
        form.add(self.tr("Surface"), self.surface)
        form.add(self.tr("Tone"), self.tone)
        form.add("", self.discontinued)
        form.add(self.tr("Notes"), self.notes)

    def _sync_grade(self) -> None:
        self.grade.setEnabled(self.contrast.value() == ContrastType.GRADED)

    def new_object(self) -> Paper:
        return Paper(name="", base=PaperBase.RC, contrast_type=ContrastType.VARIABLE,
                     surface=PaperSurface.GLOSSY, tone=PaperTone.NEUTRAL)  # fmt: skip

    def heading_for(self, obj: Paper, is_new: bool) -> str:
        return self.tr("New paper") if is_new else obj.display_name

    def populate(self, obj: Paper) -> None:
        self.manufacturer.reload()
        self.manufacturer.set_current_id(obj.manufacturer_id)
        self.name.setText(obj.name or "")
        self.base.set_value(obj.base)
        self.contrast.set_value(obj.contrast_type)
        self.grade.setCurrentText(obj.grade or "2")
        self.surface.set_value(obj.surface)
        self.tone.set_value(obj.tone)
        self.discontinued.setChecked(bool(obj.discontinued))
        self.notes.setPlainText(obj.notes or "")
        self._sync_grade()

    def validate(self) -> bool:
        ok = self.f_mfr.set_error(
            None if self.manufacturer.current_id() else self.tr("Choose a manufacturer.")
        )
        missing = not self.name.text().strip()
        return self.f_name.set_error(self.tr("Name is required.") if missing else None) and ok

    def apply(self, obj: Paper) -> None:
        mfr = self.ctx.session.get(Manufacturer, self.manufacturer.current_id())
        assert mfr is not None
        obj.manufacturer = mfr
        obj.name = self.name.text().strip()
        obj.base = self.base.value()
        obj.contrast_type = self.contrast.value()
        obj.grade = self.grade.currentText() if obj.contrast_type == ContrastType.GRADED else None
        obj.surface = self.surface.value()
        obj.tone = self.tone.value()
        obj.discontinued = self.discontinued.isChecked()
        obj.notes = self.notes.toPlainText()


class AgitationPresetForm(EditorForm):
    def build(self, form: FormBuilder) -> None:
        self.name = QLineEdit()
        self.text = QPlainTextEdit()
        self.text.setTabChangesFocus(True)
        self.text.setFixedHeight(70)
        self.order = QSpinBox()
        self.order.setRange(0, 999)
        self.order.setMaximumWidth(90)
        self.notes = notes_edit()
        self.f_name = form.add(self.tr("Name"), self.name)
        form.add(self.tr("Agitation text"), self.text)
        form.add(self.tr("Sort order"), self.order)
        form.add(self.tr("Notes"), self.notes)

    def new_object(self) -> AgitationPreset:
        return AgitationPreset(name="", text="", sort_order=100)

    def heading_for(self, obj: AgitationPreset, is_new: bool) -> str:
        return self.tr("New agitation preset") if is_new else obj.name

    def populate(self, obj: AgitationPreset) -> None:
        self.name.setText(obj.name or "")
        self.text.setPlainText(obj.text or "")
        self.order.setValue(obj.sort_order or 0)
        self.notes.setPlainText(obj.notes or "")

    def validate(self) -> bool:
        if not self.name.text().strip():
            return self.f_name.set_error(self.tr("Name is required."))
        return self.f_name.set_error(None)

    def apply(self, obj: AgitationPreset) -> None:
        obj.name = self.name.text().strip()
        obj.text = self.text.toPlainText().strip()
        obj.sort_order = self.order.value()
        obj.notes = self.notes.toPlainText()


# --------------------------------------------------------------------------- panels


class CataloguePanel(ListDetailPanel):
    """List/detail with the "in use → offer mark discontinued" delete rule."""

    def confirm_delete(self, obj: Any) -> bool:
        s = self.ctx.session
        if isinstance(obj, Chemical) and obj.is_builtin:
            QMessageBox.information(
                self, self.tr("Delete"), self.tr("Built-in entries cannot be deleted.")
            )
            return False
        n = cat.usage_count(s, obj)
        if n == 0:
            return super().confirm_delete(obj)
        if hasattr(obj, "discontinued"):
            if obj.discontinued:
                QMessageBox.information(
                    self,
                    self.tr("In use"),
                    self.tr("“{0}” is used by {1} record(s) and cannot be deleted.").format(
                        self.describe(obj), n
                    ),
                )
                return False
            btn = QMessageBox.question(
                self,
                self.tr("In use"),
                self.tr(
                    "“{0}” is used by {1} record(s) and cannot be deleted.\n\n"
                    "Mark it as discontinued instead? It will stay on existing records "
                    "but be hidden from new ones."
                ).format(self.describe(obj), n),
            )
            if btn == QMessageBox.StandardButton.Yes:
                obj.discontinued = True
                s.commit()
                self.editor.load(obj)
                self.refresh(select=obj)
                self.changed.emit()
        else:
            QMessageBox.information(
                self,
                self.tr("In use"),
                self.tr("“{0}” is used by {1} record(s) and cannot be deleted.").format(
                    self.describe(obj), n
                ),
            )
        return False


class FilmsPanel(CataloguePanel):
    def __init__(self, ctx: AppContext) -> None:
        cols = [
            Column(_tr("Manufacturer"), lambda f: f.manufacturer.name, width=110),
            Column(_tr("Name"), lambda f: f.name, width=200),
            Column(_tr("ISO"), lambda f: f.box_iso, align_right=True, width=60),
            Column(_tr("Type"), lambda f: label(f.type), width=150),
            Column(_tr("Formats"), lambda f: f.formats_available, width=120),
            Column(_tr("Aliases"), lambda f: f.aliases, width=120),
            Column(_tr("Disc."), lambda f: yes(f.discontinued), width=50),
        ]
        super().__init__(ctx, "cat_films", cols, FilmStockForm(ctx),
                         new_label=_tr("New film"))  # fmt: skip
        self.table.source.dimmed = lambda f: f.discontinued

    def fetch(self) -> Sequence[FilmStock]:
        return cat.film_stocks(self.ctx.session)


class ChemicalsPanel(CataloguePanel):
    def __init__(self, ctx: AppContext) -> None:
        cols = [
            Column(_tr("Kind"), lambda c: label(c.kind), width=140),
            Column(
                _tr("Manufacturer"),
                lambda c: c.manufacturer.name if c.manufacturer else "",
                width=110,
            ),  # fmt: skip
            Column(_tr("Name"), lambda c: c.name, width=170),
            Column(_tr("Dilutions"), lambda c: c.common_dilutions, width=150),
            Column(_tr("Form"), lambda c: label(c.form), width=70),
            Column(_tr("Disc."), lambda c: yes(c.discontinued), width=50),
        ]
        super().__init__(ctx, "cat_chemicals", cols, ChemicalForm_(ctx),
                         new_label=_tr("New chemical"))  # fmt: skip
        self.table.source.dimmed = lambda c: c.discontinued
        self.kind_filter = QComboBox()
        self.kind_filter.addItem(_tr("All kinds"), None)
        for k in ChemicalKind:
            self.kind_filter.addItem(label(k), k.value)
        self.kind_filter.currentIndexChanged.connect(self._apply_kind)
        self.filters.addWidget(self.kind_filter)
        self.table.proxy.extra_filter = self._kind_ok

    def _kind_ok(self, c: Chemical) -> bool:
        k = self.kind_filter.currentData()
        return k is None or c.kind.value == k

    def _apply_kind(self) -> None:
        self.table.proxy.refilter()

    def fetch(self) -> Sequence[Chemical]:
        return cat.chemicals(self.ctx.session)


class PapersPanel(CataloguePanel):
    def __init__(self, ctx: AppContext) -> None:
        cols = [
            Column(_tr("Manufacturer"), lambda p: p.manufacturer.name, width=110),
            Column(_tr("Name"), lambda p: p.name, width=190),
            Column(_tr("Base"), lambda p: label(p.base), width=50),
            Column(
                _tr("Contrast"),
                lambda p: label(p.contrast_type) + (f" {p.grade}" if p.grade else ""),
                width=130,
            ),  # fmt: skip
            Column(_tr("Surface"), lambda p: label(p.surface), width=80),
            Column(_tr("Tone"), lambda p: label(p.tone), width=70),
            Column(_tr("Disc."), lambda p: yes(p.discontinued), width=50),
        ]
        super().__init__(ctx, "cat_papers", cols, PaperForm(ctx),
                         new_label=_tr("New paper"))  # fmt: skip
        self.table.source.dimmed = lambda p: p.discontinued

    def fetch(self) -> Sequence[Paper]:
        return cat.papers(self.ctx.session)


class ManufacturersPanel(CataloguePanel):
    def __init__(self, ctx: AppContext) -> None:
        cols = [
            Column(_tr("Name"), lambda m: m.name, width=180),
            Column(_tr("Country"), lambda m: m.country or "", width=140),
        ]
        super().__init__(ctx, "cat_manufacturers", cols, ManufacturerForm(ctx),
                         new_label=_tr("New manufacturer"))  # fmt: skip

    def fetch(self) -> Sequence[Manufacturer]:
        return cat.manufacturers(self.ctx.session)


class PresetsPanel(CataloguePanel):
    def __init__(self, ctx: AppContext) -> None:
        cols = [
            Column(_tr("#"), lambda a: a.sort_order, align_right=True, width=40),
            Column(_tr("Name"), lambda a: a.name, width=180),
            Column(_tr("Text"), lambda a: a.text, width=360),
        ]
        super().__init__(ctx, "cat_presets", cols, AgitationPresetForm(ctx),
                         new_label=_tr("New preset"))  # fmt: skip

    def fetch(self) -> Sequence[AgitationPreset]:
        return cat.agitation_presets(self.ctx.session)


class CatalogueView(BaseView):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.title = self.tr("Catalogue")
        self.tabs = QTabWidget()
        self.panels: list[ListDetailPanel] = [
            FilmsPanel(ctx),
            ChemicalsPanel(ctx),
            PapersPanel(ctx),
            ManufacturersPanel(ctx),
            PresetsPanel(ctx),
        ]
        names = [
            self.tr("Films"),
            self.tr("Chemicals"),
            self.tr("Papers"),
            self.tr("Manufacturers"),
            self.tr("Agitation presets"),
        ]
        for p, n in zip(self.panels, names, strict=True):
            self.tabs.addTab(p, n)
            p.changed.connect(self._on_changed)
        self.tabs.currentChanged.connect(lambda _: self.current().refresh())
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)

    def current(self) -> ListDetailPanel:
        w = self.tabs.currentWidget()
        assert isinstance(w, ListDetailPanel)
        return w

    def _on_changed(self) -> None:
        # Manufacturer edits affect the other lists' display names.
        for p in self.panels:
            if p is not self.current():
                p.refresh()

    def refresh(self) -> None:
        self.current().refresh()

    def new_item(self) -> None:
        self.current().new_item()

    def focus_search(self) -> None:
        self.current().focus_search()

    def save(self) -> None:
        self.current().save()

    def shutdown(self) -> None:
        for p in self.panels:
            p.shutdown()


class EditorDialog(QDialog):
    """Wraps an EditorForm in a small modal dialog (e.g. "+ New film stock…")."""

    def __init__(self, form: EditorForm, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = form
        self.result_obj: Any = None
        layout = QVBoxLayout(self)
        layout.addWidget(form)
        form.saved.connect(self._done)
        form.cancelled.connect(self.reject)
        form.load(None)
        self.resize(480, 520)

    def _done(self, obj: Any) -> None:
        self.result_obj = obj
        self.accept()
