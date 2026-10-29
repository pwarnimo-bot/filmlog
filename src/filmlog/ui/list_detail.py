# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generic master/detail page: searchable table on the left, editor form on the right."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from filmlog.ui.context import AppContext
from filmlog.ui.editor import EditorForm
from filmlog.ui.flow_layout import flow_container
from filmlog.ui.table_model import Column, ObjectTable


class ListDetailPanel(QWidget):
    """Reusable list + editor. Subclasses implement ``fetch`` and optionally ``delete``."""

    changed = Signal()  # data changed (saved or deleted)

    def __init__(
        self,
        ctx: AppContext,
        name: str,
        columns: Sequence[Column],
        editor: EditorForm,
        *,
        new_label: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.editor = editor

        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Search…  (Ctrl+F)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)

        self.table = ObjectTable(name, columns, ctx.settings)
        self.table.selectionModel().selectionChanged.connect(self._on_current)
        self.table.delete_action.triggered.connect(self.delete_current)

        self.new_button = QPushButton(new_label or self.tr("New"))
        self.new_button.setToolTip(self.tr("Create a new entry (Ctrl+N)"))
        self.new_button.clicked.connect(self.new_item)
        self.delete_button = QPushButton(self.tr("Delete"))
        self.delete_button.setToolTip(self.tr("Delete the selected entry (Del)"))
        self.delete_button.clicked.connect(self.delete_current)

        self.toolbar = QHBoxLayout()
        self.toolbar.addWidget(self.search, 1)
        self.toolbar.addWidget(self.new_button)
        self.toolbar.addWidget(self.delete_button)
        # Filters wrap onto extra lines in narrow windows; shown once a view adds some.
        self.filter_bar, self.filters = flow_container()
        self.filter_bar.hide()

        left = QWidget()
        left.setMinimumWidth(280)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addLayout(self.toolbar)
        lv.addWidget(self.filter_bar)
        lv.addWidget(self.table, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.detail_widget())
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self._name = name
        self._restore_splitter()
        self.splitter.setChildrenCollapsible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        editor.saved.connect(self._on_saved)
        editor.cancelled.connect(self._on_cancelled)
        editor.clear()
        self._suppress = False

    def detail_widget(self) -> QWidget:
        """The right-hand side; override to wrap the editor (e.g. in tabs)."""
        return self.editor

    # -- data --------------------------------------------------------------

    def fetch(self) -> Sequence[Any]:
        raise NotImplementedError

    def refresh(self, select: Any = None) -> None:
        self.filter_bar.setVisible(self.filters.count() > 0)
        self._suppress = True
        try:
            self.table.set_items(self.fetch(), keep=select)
        finally:
            self._suppress = False
        current = self.table.current_object()
        if current is not None and current is not self.editor.obj and not self.editor.dirty:
            self.editor.load(current)
        elif current is None and not self.editor.is_new() and not self.editor.dirty:
            self.editor.clear()
        self.delete_button.setEnabled(current is not None)

    def _on_search(self, text: str) -> None:
        self.table.proxy.set_text(text)

    def _on_current(self, *_: Any) -> None:
        if self._suppress:
            return
        obj = self.table.current_object()
        self.delete_button.setEnabled(obj is not None)
        if obj is self.editor.obj:
            return
        if not self.maybe_discard():
            # Go back to the record being edited.
            self._suppress = True
            if self.editor.obj is not None and not self.editor.is_new():
                self.table.select_object(self.editor.obj)
            else:
                self.table.clearSelection()
            self._suppress = False
            return
        if obj is not None:
            self.editor.load(obj)
        else:
            self.editor.clear()

    def _on_saved(self, obj: Any) -> None:
        self.refresh(select=obj)
        self.changed.emit()

    def _on_cancelled(self) -> None:
        if self.editor.obj is None:
            self.table.clearSelection()

    # -- actions -----------------------------------------------------------

    def maybe_discard(self) -> bool:
        """Ask about unsaved changes before leaving the current record."""
        return self.editor.maybe_discard()

    def new_item(self) -> None:
        if not self.maybe_discard():
            return
        self._suppress = True
        self.table.clearSelection()
        self._suppress = False
        self.editor.load(None)
        self.editor.focus_first()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def save(self) -> None:
        if self.editor.obj is not None:
            self.editor.save()

    def describe(self, obj: Any) -> str:
        return str(getattr(obj, "display_name", obj))

    def confirm_delete(self, obj: Any) -> bool:
        """Return True if ``obj`` may be deleted (ask the user). Override for checks."""
        btn = QMessageBox.question(
            self,
            self.tr("Delete"),
            self.tr("Delete “{0}”? This cannot be undone.").format(self.describe(obj)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return btn == QMessageBox.StandardButton.Yes

    def before_delete(self, obj: Any) -> None:
        """Hook to clean up (e.g. image files) right before the row is deleted."""

    def delete_current(self) -> None:
        obj = self.table.current_object()
        if obj is None or not self.confirm_delete(obj):
            return
        self.before_delete(obj)
        session = self.ctx.session
        session.delete(obj)
        session.commit()
        self.editor.clear()
        self.refresh()
        self.changed.emit()

    def set_split(self, left: int, right: int) -> None:
        """Default proportions, unless the user's own sizes were restored."""
        if f"{self._name}__split" not in self.ctx.settings.table_states:
            self.splitter.setSizes([left * 100, right * 100])

    def _restore_splitter(self) -> None:
        state = self.ctx.settings.table_states.get(f"{self._name}__split")
        if state:
            self.splitter.restoreState(QByteArray.fromBase64(state.encode()))

    def shutdown(self) -> None:
        self.table.save_state()
        data = bytes(self.splitter.saveState().toBase64().data()).decode()
        self.ctx.settings.table_states[f"{self._name}__split"] = data
