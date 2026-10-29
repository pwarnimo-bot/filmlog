# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prints view: every print across rolls, filterable, editable in place."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QCoreApplication, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QMessageBox, QVBoxLayout, QWidget

from filmlog.db.enums import ChemicalKind, ContrastMethod
from filmlog.db.models import Print
from filmlog.services import catalogue as cat
from filmlog.services.images import delete_unreferenced
from filmlog.services.prints import PrintFilter, contrast_summary, list_prints, total_exposure
from filmlog.services.timefmt import format_seconds
from filmlog.ui.base_view import BaseView
from filmlog.ui.context import AppContext
from filmlog.ui.labels import label
from filmlog.ui.list_detail import ListDetailPanel
from filmlog.ui.print_form import PrintForm
from filmlog.ui.table_model import Column
from filmlog.ui.widgets import stars


def _tr(text: str) -> str:
    return QCoreApplication.translate("PrintsView", text)


class PrintsPanel(ListDetailPanel):
    openRoll = Signal(int)  # noqa: N815

    def __init__(self, ctx: AppContext) -> None:
        cols = [
            Column(_tr("Roll"), lambda p: p.roll.code, width=80),
            Column(_tr("Frame"), lambda p: p.frame, width=50),
            Column(_tr("Title"), lambda p: p.title, width=130),
            Column(_tr("Date"), lambda p: p.date_printed or "", width=85),
            Column(_tr("Paper"), lambda p: p.paper.display_name if p.paper else "", width=200),
            Column(_tr("Size"), lambda p: p.paper_size, width=70),
            Column(
                _tr("Contrast"),
                lambda p: contrast_summary(p.contrast_method, p.exposures),
                width=190,
            ),  # fmt: skip
            Column(
                _tr("Total"),
                lambda p: format_seconds(total_exposure(p.exposures)),
                sort=lambda p: total_exposure(p.exposures),
                align_right=True,
                width=55,
            ),  # fmt: skip
            Column(
                _tr("Rating"), lambda p: stars(p.rating), sort=lambda p: p.rating or 0, width=80
            ),  # fmt: skip
            Column(
                _tr("Final"),
                lambda p: "",
                sort=lambda p: p.is_final,
                width=60,
                chip=lambda p: (_tr("Final"), "final") if p.is_final else None,
            ),  # fmt: skip
        ]
        self.print_form = PrintForm(ctx)
        super().__init__(ctx, "prints", cols, self.print_form, new_label=_tr("New print"))
        self.set_split(55, 45)
        self.print_form.openRoll.connect(self.openRoll)
        self._build_filters()

    def _build_filters(self) -> None:
        self.f_paper = QComboBox()
        self.f_dev = QComboBox()
        self.f_method = QComboBox()
        self.f_rating = QComboBox()
        self.f_final = QCheckBox(_tr("Final only"))
        for c in (self.f_paper, self.f_dev, self.f_method, self.f_rating):
            c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            c.setMaximumWidth(190)
            c.currentIndexChanged.connect(lambda _: self.refresh())
            self.filters.addWidget(c)
        self.f_final.toggled.connect(lambda _: self.refresh())
        self.filters.addWidget(self.f_final)
        self.f_method.addItem(_tr("Any contrast"), None)
        for m in ContrastMethod:
            self.f_method.addItem(label(m), m.value)
        self.f_rating.addItem(_tr("Any rating"), None)
        for i in range(1, 6):
            self.f_rating.addItem("★" * i + "+", i)
        self._fill_filters()

    def _fill_filters(self) -> None:
        s = self.ctx.session
        for combo, all_label, items in (
            (self.f_paper, _tr("Any paper"),
             [(p.id, p.display_name) for p in cat.papers(s)]),
            (self.f_dev, _tr("Any developer"),
             [(c.id, c.display_name) for c in cat.chemicals(s, [ChemicalKind.PAPER_DEVELOPER])]),
        ):  # fmt: skip
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(all_label, None)
            for value, text in items:
                combo.addItem(text, value)
            combo.setCurrentIndex(max(0, combo.findData(current)) if current else 0)
            combo.blockSignals(False)

    def fetch(self) -> Sequence[Print]:
        m = self.f_method.currentData()
        flt = PrintFilter(
            paper_id=self.f_paper.currentData(),
            developer_id=self.f_dev.currentData(),
            contrast_method=ContrastMethod(m) if m else None,
            final_only=self.f_final.isChecked(),
            min_rating=self.f_rating.currentData(),
        )
        return list_prints(self.ctx.session, flt)

    def refresh(self, select: Any = None) -> None:
        self._fill_filters()
        super().refresh(select)

    def describe(self, obj: Any) -> str:
        return _tr("print of {0} frame {1}").format(obj.roll.code, obj.frame or "?")

    def confirm_delete(self, obj: Any) -> bool:
        extra = _tr(" Its attached image will be deleted too.") if obj.image else ""
        btn = QMessageBox.question(
            self,
            _tr("Delete print"),
            _tr("Delete the {0}?").format(self.describe(obj)) + extra,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return btn == QMessageBox.StandardButton.Yes

    def before_delete(self, obj: Any) -> None:
        self._pending_image = obj.image
        self._pending_roll = obj.roll

    def delete_current(self) -> None:
        self._pending_image = None
        self._pending_roll = None
        super().delete_current()
        if self._pending_roll is not None:
            self.ctx.session.expire(self._pending_roll, ["prints"])
        delete_unreferenced(self.ctx.session, [self._pending_image])


class PrintsView(BaseView):
    openRoll = Signal(int)  # noqa: N815

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = self.tr("Prints")
        self.panel = PrintsPanel(ctx)
        self.panel.openRoll.connect(self.openRoll)
        self.panel.table.doubleClicked.connect(lambda _: self.panel.editor.focus_first())
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel)

    def refresh(self) -> None:
        self.panel.refresh()

    def new_item(self) -> None:
        self.panel.new_item()

    def focus_search(self) -> None:
        self.panel.focus_search()

    def save(self) -> None:
        self.panel.save()

    def shutdown(self) -> None:
        self.panel.shutdown()
