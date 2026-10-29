# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rolls view (main screen): roll list with filters + Roll / Development / Prints tabs."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from filmlog.db.enums import CameraStatus, ChemicalKind, FilmFormat, RollStatus
from filmlog.db.models import Camera, FilmStock, Roll
from filmlog.services import catalogue as cat
from filmlog.services import rolls as roll_service
from filmlog.services.cameras import list_cameras
from filmlog.services.images import delete_unreferenced, images_of_roll
from filmlog.services.pushpull import compute_stops
from filmlog.ui.base_view import BaseView
from filmlog.ui.catalogue_view import EditorDialog, FilmStockForm, notes_edit
from filmlog.ui.context import AppContext
from filmlog.ui.development_form import DevelopmentTab
from filmlog.ui.editor import EditorForm
from filmlog.ui.labels import label
from filmlog.ui.list_detail import ListDetailPanel
from filmlog.ui.roll_tabs import ImagesTab, PrintsTab
from filmlog.ui.table_model import Column
from filmlog.ui.widgets import (
    Badge,
    EnumCombo,
    FormBuilder,
    ListCompleter,
    OptionalDateEdit,
    OptionalIntSpin,
    RefCombo,
    StopsSpin,
    push_pull_badge,
    row,
    set_completions,
)


def _tr(text: str) -> str:
    return QCoreApplication.translate("Rolls", text)


def status_chip(roll: Roll) -> tuple[str, str]:
    return label(roll.status), roll.status.value


def ei_chip(roll: Roll) -> tuple[str, str]:
    return push_pull_badge(roll.push_pull_stops)


# --------------------------------------------------------------------------- roll form


class RollForm(EditorForm):
    def build(self, form: FormBuilder) -> None:
        self._prev_box_iso: int | None = None

        self.code = QLineEdit()
        self.code.setMaximumWidth(160)
        self.title = QLineEdit()
        self.title.setPlaceholderText(self.tr("optional, e.g. “Moselle walk”"))
        self.film = RefCombo(allow_none=False, new_label=self.tr("+ New film stock…"))
        self.film.newRequested.connect(self._new_film)
        self.film.currentIndexChanged.connect(self._film_changed)
        self.camera = RefCombo(none_label=self.tr("— no camera —"))
        self.camera.currentIndexChanged.connect(self._camera_changed)
        self.format = EnumCombo(FilmFormat)
        self.exposures = OptionalIntSpin(1, 999)
        self.ei = QSpinBox()
        self.ei.setRange(1, 100000)
        self.ei.setMaximumWidth(110)
        self.ei.valueChanged.connect(self._ei_changed)
        self.stops = StopsSpin()
        self.stops.valueChanged.connect(self._update_badge)
        self.badge = Badge()
        self.lens = QLineEdit()
        self.expiry = OptionalDateEdit()
        self.expiry.dateChanged.connect(self._update_expired)
        self.expired = Badge()
        self.loaded = OptionalDateEdit()
        self.loaded.dateChanged.connect(self._update_expired)
        self.finished = OptionalDateEdit()
        self.subject = QLineEdit()
        self.status = EnumCombo(RollStatus)
        self.tags = QLineEdit()
        self.tags.setPlaceholderText(self.tr("comma-separated, e.g. street, family"))
        self.tag_completer = ListCompleter([], self.tags)
        self.notes = notes_edit()
        self.notes.setFixedHeight(110)

        self.f_code = form.add(self.tr("Code"), self.code)
        form.add(self.tr("Title"), self.title)
        self.f_film = form.add(self.tr("Film"), self.film)
        form.add(self.tr("Camera"), self.camera)
        form.add(self.tr("Lens"), self.lens)
        form.add(self.tr("Format"), row(self.format, self.tr("Exposures"), self.exposures),
                 self.format, self.exposures)  # fmt: skip
        self.f_ei = form.add(
            self.tr("EI (shot at)"),
            row(self.ei, self.tr("Push/pull"), self.stops, self.badge),
            self.ei,
            self.stops,
        )
        self.f_status = form.add(self.tr("Status"), self.status)
        form.add(self.tr("Subject / location"), self.subject)
        form.add(self.tr("Tags"), self.tags)
        form.section(self.tr("Dates"))
        form.add(self.tr("Loaded"), row(self.loaded, self.tr("Finished"), self.finished),
                 self.loaded, self.finished)  # fmt: skip
        form.add(self.tr("Film expiry"), row(self.expiry, self.expired), self.expiry)
        form.add(self.tr("Notes"), self.notes)

    # -- reference data ---------------------------------------------------------

    def _reload_refs(self, obj: Roll) -> None:
        s = self.ctx.session
        films = [f for f in cat.film_stocks(s) if not f.discontinued or f.id == obj.film_stock_id]
        self.film.set_items(((f.id, f.display_name) for f in films), keep=False)
        cams = list_cameras(s)
        self.camera.set_items(
            ((c.id, c.display_name) for c in cams),
            greyed=[c.id for c in cams if c.status != CameraStatus.ACTIVE],
            keep=False,
        )
        self.tag_completer.set_words([t.name for t in roll_service.all_tags(s)])

    def _new_film(self) -> None:
        dlg = EditorDialog(FilmStockForm(self.ctx), self.tr("New film stock"), self)
        if dlg.exec() and isinstance(dlg.result_obj, FilmStock):
            f = dlg.result_obj
            assert isinstance(self.obj, Roll)
            current = self.obj.film_stock_id
            films = [
                x
                for x in cat.film_stocks(self.ctx.session)
                if not x.discontinued or x.id == current
            ]
            self.film.set_items(((x.id, x.display_name) for x in films), keep=False)
            self.film.set_current_id(f.id)
            self._mark_dirty()

    # -- behaviour ------------------------------------------------------------

    def _film(self) -> FilmStock | None:
        fid = self.film.current_id()
        return self.ctx.session.get(FilmStock, fid) if fid else None

    def _film_changed(self) -> None:
        film = self._film()
        if film is None or self._loading:
            self._prev_box_iso = film.box_iso if film else None
            return
        # Follow the film's box speed unless the user set a different EI.
        if self._prev_box_iso is None or self.ei.value() == self._prev_box_iso:
            self.ei.setValue(film.box_iso)
        self._prev_box_iso = film.box_iso
        self._recalc_stops()

    def _ei_changed(self) -> None:
        if not self._loading:
            self._recalc_stops()

    def _recalc_stops(self) -> None:
        film = self._film()
        if film is not None:
            self.stops.setValue(compute_stops(self.ei.value(), film.box_iso))
        self._update_badge()

    def _update_badge(self) -> None:
        text, kind = push_pull_badge(self.stops.value())
        self.badge.set(text, kind)

    def _camera_changed(self) -> None:
        cid = self.camera.current_id()
        cam = self.ctx.session.get(Camera, cid) if cid else None
        set_completions(self.lens, cam.lens_list if cam else [])
        if cam is not None and not self._loading:
            self.format.set_value(cam.format)
            lenses = cam.lens_list
            if len(lenses) == 1 and not self.lens.text().strip():
                self.lens.setText(lenses[0])

    def _update_expired(self) -> None:
        exp = self.expiry.value()
        ref = self.loaded.value() or dt.date.today()
        self.expired.set(self.tr("Expired") if exp and exp < ref else "", "expired")

    # -- EditorForm -----------------------------------------------------------

    def new_object(self) -> Roll:
        s = self.ctx.session
        roll = Roll(
            code=roll_service.suggest_code(s),
            status=RollStatus.LOADED,
            date_loaded=dt.date.today(),
            format=FilmFormat.F135,
        )
        return roll

    def heading_for(self, obj: Roll, is_new: bool) -> str:
        if is_new:
            return self.tr("New roll")
        return f"{obj.code}  {obj.title}".strip()

    def populate(self, obj: Roll) -> None:
        self._reload_refs(obj)
        self.code.setText(obj.code or "")
        self.title.setText(obj.title or "")
        if obj.film_stock_id is None:
            self.film.setCurrentIndex(-1)
            self.film.setEditText("")
        else:
            self.film.set_current_id(obj.film_stock_id)
        film = self._film()
        self._prev_box_iso = film.box_iso if film else None
        self.camera.set_current_id(obj.camera_id)
        self.format.set_value(obj.format)
        self.exposures.set_value(obj.exposures)
        self.ei.setValue(obj.shot_iso or (film.box_iso if film else 100))
        self.stops.setValue(obj.push_pull_stops or 0.0)
        self._update_badge()
        self.lens.setText(obj.lens or "")
        self.expiry.set_value(obj.film_expiry)
        self.loaded.set_value(obj.date_loaded)
        self.finished.set_value(obj.date_finished)
        self.subject.setText(obj.subject_location or "")
        self.status.set_value(obj.status)
        self.tags.setText(", ".join(t.name for t in obj.tags) if obj.id is not None else "")
        self.notes.setPlainText(obj.notes or "")
        self._update_expired()
        for f in (self.f_code, self.f_film, self.f_ei, self.f_status):
            f.set_error(None)

    def validate(self) -> bool:
        s = self.ctx.session
        code = self.code.text().strip()
        if not code:
            ok = self.f_code.set_error(self.tr("Code is required."))
        elif roll_service.code_exists(s, code, exclude_id=self.obj.id):
            ok = self.f_code.set_error(self.tr("Another roll already uses this code."))
        else:
            ok = self.f_code.set_error(None)
        ok = (
            self.f_film.set_error(
                None if self.film.current_id() else self.tr("Choose the film stock.")
            )
            and ok
        )
        status = self.status.value()
        has_dev = self.obj.id is not None and self.obj.development is not None
        if has_dev and status != RollStatus.DEVELOPED:
            ok = (
                self.f_status.set_error(
                    self.tr("This roll has a development record; delete it first to change status.")
                )
                and ok
            )
        else:
            self.f_status.set_error(None)
        return ok

    def apply(self, obj: Roll) -> None:
        s = self.ctx.session
        obj.code = self.code.text().strip()
        obj.title = self.title.text().strip()
        film = self._film()
        assert film is not None
        obj.film_stock = film
        cid = self.camera.current_id()
        obj.camera = s.get(Camera, cid) if cid else None
        obj.format = self.format.value()
        obj.exposures = self.exposures.value_or_none()
        obj.shot_iso = self.ei.value()
        obj.push_pull_stops = round(self.stops.value(), 2)
        obj.lens = self.lens.text().strip()
        obj.film_expiry = self.expiry.value()
        obj.date_loaded = self.loaded.value()
        obj.date_finished = self.finished.value()
        obj.subject_location = self.subject.text().strip()
        obj.status = self.status.value()
        obj.tags = roll_service.get_or_create_tags(s, roll_service.parse_tags(self.tags.text()))
        obj.notes = self.notes.toPlainText()

    def after_save(self, obj: Any, is_new: bool) -> None:
        roll_service.prune_unused_tags(self.ctx.session)
        self.ctx.session.commit()


# --------------------------------------------------------------------------- panel


class RollsPanel(ListDetailPanel):
    def __init__(self, ctx: AppContext) -> None:
        # Status sits next to the code so it stays visible in narrow windows.
        cols = [
            Column(_tr("Code"), lambda r: r.code, width=78),
            Column(
                _tr("Status"),
                lambda r: "",
                sort=lambda r: list(RollStatus).index(r.status),
                width=88,
                chip=status_chip,
            ),  # fmt: skip
            Column(_tr("Title"), lambda r: r.title, width=120),
            Column(_tr("Film"), lambda r: r.film_stock.display_name, width=150),
            Column(_tr("EI"), lambda r: r.shot_iso, width=125, chip=ei_chip),
            Column(_tr("Camera"), lambda r: r.camera.display_name if r.camera else "", width=110),
            Column(
                _tr("Developed"),
                lambda r: r.development.date_developed if r.development else "",
                width=85,
            ),  # fmt: skip
            Column(
                _tr("Prints"),
                lambda r: len(r.prints) or "",
                sort=lambda r: len(r.prints),
                align_right=True,
                width=45,
            ),  # fmt: skip
        ]
        self.roll_form = RollForm(ctx)
        super().__init__(ctx, "rolls_v2", cols, self.roll_form, new_label=_tr("New roll"))
        self.set_split(42, 58)
        self._build_filters()
        self.roll_form.saved.connect(lambda _: self._update_detail())
        self.dev_tab.form.saved.connect(self._dev_saved)
        self.dev_tab.form.cancelled.connect(self._dev_cancelled)
        self.dev_tab.delete_button.clicked.connect(self._delete_development)

    # -- layout -------------------------------------------------------------

    def detail_widget(self) -> QWidget:
        self.mark_button = QPushButton(_tr("Mark as developed"))
        self.mark_button.setProperty("role", "primary")
        self.mark_button.setToolTip(
            _tr("Record the development, pre-filled from your last matching roll")
        )
        self.mark_button.clicked.connect(self.mark_developed)
        self.header = QLabel()
        self.header.setProperty("role", "page-title")
        # Long titles get clipped rather than widening the window.
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.header.setMinimumWidth(60)
        self.status_badge = Badge()
        self.ei_badge = Badge()
        head = QHBoxLayout()
        head.addWidget(self.header, 1)
        head.addWidget(self.ei_badge)
        head.addWidget(self.status_badge)
        head.addWidget(self.mark_button)

        self.tabs = QTabWidget()
        self.dev_tab = DevelopmentTab(self.ctx)
        self.prints_tab = PrintsTab(self.ctx)
        self.images_tab = ImagesTab(self.ctx)
        self.tabs.addTab(self.editor, _tr("Roll"))
        self.tabs.addTab(self.dev_tab, _tr("Development"))
        self.tabs.addTab(self.prints_tab, _tr("Prints"))
        self.tabs.addTab(self.images_tab, _tr("Images"))
        self.prints_tab.changed.connect(self._prints_changed)
        self.images_tab.changed.connect(self._prints_changed)
        self.editor.heading.hide()

        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 0, 0, 0)
        v.addLayout(head)
        v.addWidget(self.tabs, 1)
        return w

    def _build_filters(self) -> None:
        self.f_status = QComboBox()
        self.f_film = QComboBox()
        self.f_camera = QComboBox()
        self.f_developer = QComboBox()
        self.f_year = QComboBox()
        self.f_tag = QComboBox()
        self._filter_combos = (
            self.f_status, self.f_film, self.f_camera, self.f_developer, self.f_year, self.f_tag,
        )  # fmt: skip
        for c in self._filter_combos:
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            c.setMaximumWidth(170)
            c.currentIndexChanged.connect(self._filters_changed)
            self.filters.addWidget(c)
        self.clear_filters = QPushButton(_tr("Clear"))
        self.clear_filters.clicked.connect(self._clear_filters)
        self.filters.addWidget(self.clear_filters)
        self._fill_filters()

    def _fill_filters(self) -> None:
        s = self.ctx.session

        def fill(combo: QComboBox, all_label: str, items: Sequence[tuple[Any, str]]) -> None:
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(all_label, None)
            for value, text in items:
                combo.addItem(text, value)
            idx = combo.findData(current) if current is not None else 0
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)

        fill(self.f_status, _tr("Any status"), [(st.value, label(st)) for st in RollStatus])
        used_films = {r.film_stock_id for r in roll_service.list_rolls(s)}
        films = [(f.id, f.display_name) for f in cat.film_stocks(s) if f.id in used_films]
        fill(self.f_film, _tr("Any film"), films)
        fill(self.f_camera, _tr("Any camera"), [(c.id, c.display_name) for c in list_cameras(s)])
        devs = cat.chemicals(s, [ChemicalKind.FILM_DEVELOPER])
        fill(self.f_developer, _tr("Any developer"), [(c.id, c.display_name) for c in devs])
        fill(self.f_year, _tr("Any year"), [(y, str(y)) for y in roll_service.roll_years(s)])
        fill(self.f_tag, _tr("Any tag"), [(t.id, t.name) for t in roll_service.all_tags(s)])

    def _filters_changed(self) -> None:
        self.refresh()

    def _clear_filters(self) -> None:
        for c in self._filter_combos:
            c.blockSignals(True)
            c.setCurrentIndex(0)
            c.blockSignals(False)
        self.search.clear()
        self.refresh()

    def fetch(self) -> Sequence[Roll]:
        st = self.f_status.currentData()
        flt = roll_service.RollFilter(
            status=RollStatus(st) if st else None,
            film_stock_id=self.f_film.currentData(),
            camera_id=self.f_camera.currentData(),
            developer_id=self.f_developer.currentData(),
            year=self.f_year.currentData(),
            tag_id=self.f_tag.currentData(),
        )
        return roll_service.list_rolls(self.ctx.session, flt)

    def refresh(self, select: Any = None) -> None:
        self._fill_filters()
        super().refresh(select)
        self._update_detail()

    # -- detail sync ----------------------------------------------------------

    def current_roll(self) -> Roll | None:
        obj = self.roll_form.obj
        return obj if isinstance(obj, Roll) else None

    def _on_current(self, *args: Any) -> None:
        before = self.roll_form.obj
        super()._on_current(*args)
        if self.roll_form.obj is not before:
            self._update_detail()

    def maybe_discard(self) -> bool:
        return self.roll_form.maybe_discard() and self.dev_tab.form.maybe_discard()

    def new_item(self) -> None:
        super().new_item()
        self.tabs.setCurrentIndex(0)
        self._update_detail()
        self.roll_form.film.setFocus()

    def _update_detail(self) -> None:
        roll = self.current_roll()
        saved = roll is not None and roll.id is not None
        if roll is None:
            self.header.setText("")
            self.status_badge.set("", "box")
            self.ei_badge.set("", "box")
        else:
            self.header.setText(
                f"{roll.code}  <span style='font-weight:normal'>{roll.title}</span>"
                if saved else _tr("New roll")
            )  # fmt: skip
            if saved:
                self.status_badge.set(label(roll.status), roll.status.value)
                text, kind = push_pull_badge(roll.push_pull_stops)
                self.ei_badge.set(f"EI {roll.shot_iso} · {text}", kind)
            else:
                self.status_badge.set("", "box")
                self.ei_badge.set("", "box")
        developing = self.dev_tab.form.is_new() and self.dev_tab.form.roll is roll
        self.mark_button.setVisible(
            saved and roll is not None and roll.development is None and not developing
        )
        for i in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(i, saved)
        self._update_dev_tab()
        self.prints_tab.set_roll(roll if saved else None)
        self.images_tab.set_roll(roll if saved else None)
        if roll is not None and saved:
            n = len(roll.prints)
            self.tabs.setTabText(2, _tr("Prints ({0})").format(n) if n else _tr("Prints"))

    def _prints_changed(self) -> None:
        roll = self.current_roll()
        self._suppress = True
        try:
            self.table.set_items(self.fetch(), keep=roll)
        finally:
            self._suppress = False
        if roll is not None:
            n = len(roll.prints)
            self.tabs.setTabText(2, _tr("Prints ({0})").format(n) if n else _tr("Prints"))
        self.changed.emit()

    def _update_dev_tab(self) -> None:
        roll = self.current_roll()
        if roll is None or roll.id is None:
            self.dev_tab.show_message("")
            return
        if self.dev_tab.form.is_new() and self.dev_tab.form.roll is roll:
            return  # keep the unsaved development being entered
        if roll.development is not None:
            self.dev_tab.show_form(roll)
        else:
            msg = _tr("This roll hasn’t been developed yet.")
            if roll.status == RollStatus.DEVELOPED:
                msg = _tr("No development recorded for this roll yet.")
            self.dev_tab.show_message(
                msg + "\n\n" + _tr("Use “Mark as developed” to record how it was processed.")
            )

    # -- development flow ---------------------------------------------------------

    def mark_developed(self) -> None:
        roll = self.current_roll()
        if roll is None:
            return
        if self.roll_form.dirty and not self.roll_form.save():
            self.tabs.setCurrentIndex(0)
            return
        if roll.id is None or roll.development is not None:
            return
        self.dev_tab.show_form(roll)
        self.mark_button.hide()
        self.tabs.setCurrentWidget(self.dev_tab)
        self.dev_tab.form.date.setFocus()

    def _dev_saved(self, _: Any) -> None:
        roll = self.current_roll()
        self.refresh(select=roll)
        if roll is not None:
            self.roll_form.load(roll)
        self.dev_tab.delete_button.setEnabled(True)

    def _dev_cancelled(self) -> None:
        self._update_detail()

    def _delete_development(self) -> None:
        roll = self.current_roll()
        if roll is None or roll.development is None:
            return
        btn = QMessageBox.question(
            self,
            _tr("Delete development"),
            _tr(
                "Delete the development record of roll {0}? The roll goes back to “exposed”."
            ).format(roll.code),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        s = self.ctx.session
        dev = roll.development
        roll.development = None
        s.delete(dev)
        roll.status = RollStatus.EXPOSED
        s.commit()
        self.roll_form.load(roll)
        self.refresh(select=roll)

    # -- delete roll -----------------------------------------------------------------

    def describe(self, obj: Any) -> str:
        return obj.code

    def before_delete(self, obj: Any) -> None:
        self._pending_images = images_of_roll(obj)

    def confirm_delete(self, obj: Any) -> bool:
        assert isinstance(obj, Roll)
        n_img = len(images_of_roll(obj))
        if n_img and not obj.prints:
            btn = QMessageBox.question(
                self,
                _tr("Delete roll"),
                _tr("Delete roll {0}? Its {1} attached image(s) will be deleted too.").format(
                    obj.code, n_img
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return btn == QMessageBox.StandardButton.Yes
        if obj.prints:
            lines = "\n".join(
                f"  • {_tr('frame')} {p.frame or '?'}"
                + (f" — {p.title}" if p.title else "")
                + (f" ({p.date_printed})" if p.date_printed else "")
                for p in obj.prints[:15]
            )
            more = len(obj.prints) - 15
            if more > 0:
                lines += "\n  " + _tr("… and {0} more").format(more)
            text = _tr(
                "Roll {0} has {1} print(s) which will be deleted too:\n\n{2}\n\n"
                "Delete the roll and all its prints?"
            ).format(obj.code, len(obj.prints), lines)
            if n_img:
                text += "\n" + _tr("{0} attached image(s) will be deleted as well.").format(n_img)
            btn = QMessageBox.warning(
                self,
                _tr("Delete roll"),
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return btn == QMessageBox.StandardButton.Yes
        return super().confirm_delete(obj)

    def delete_current(self) -> None:
        self._pending_images = []
        super().delete_current()
        delete_unreferenced(self.ctx.session, self._pending_images)
        roll_service.prune_unused_tags(self.ctx.session)
        self.ctx.session.commit()
        self._update_detail()

    def select_roll(self, roll_id: int) -> None:
        roll = self.ctx.session.get(Roll, roll_id)
        if roll is None or not self.maybe_discard():
            return
        self._clear_filters()
        self.table.select_object(roll)


class RollsView(BaseView):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = self.tr("Rolls")
        self.panel = RollsPanel(ctx)
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel)

    def refresh(self) -> None:
        self.panel.refresh()

    def new_item(self) -> None:
        self.panel.new_item()

    def focus_search(self) -> None:
        self.panel.focus_search()

    def save(self) -> None:
        if self.panel.tabs.currentWidget() is self.panel.dev_tab:
            if self.panel.dev_tab.form.obj is not None:
                self.panel.dev_tab.form.save()
        else:
            self.panel.save()

    def shutdown(self) -> None:
        self.panel.shutdown()
        self.panel.dev_tab.past.table.save_state()

    def select_roll(self, roll_id: int) -> None:
        self.panel.select_roll(roll_id)
