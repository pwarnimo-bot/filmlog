"""Base class for record editor forms (load → edit → validate → save)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from filmlog.ui.context import AppContext
from filmlog.ui.widgets import FormBuilder, connect_changed


class EditorForm(QWidget):
    """Subclasses implement ``build``, ``populate``, ``validate``, ``apply``, ``new_object``."""

    saved = Signal(object)
    cancelled = Signal()
    dirtyChanged = Signal(bool)  # noqa: N815

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.obj: Any = None
        self._dirty = False
        self._loading = False

        self.heading = QLabel()
        self.heading.setProperty("role", "page-title")
        self.error = QLabel()
        self.error.setProperty("hint", True)
        self.error.setWordWrap(True)
        self.error.hide()

        body = QWidget()
        self.body_layout = QVBoxLayout(body)
        self.form = FormBuilder()
        self.body_layout.addLayout(self.form.layout)
        self.build(self.form)
        self.body_layout.addStretch(1)
        self.focus_chain = self.form.finish()
        connect_changed(self.focus_chain + self.extra_change_widgets(), self._mark_dirty)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)

        self.save_button = QPushButton(self.tr("Save"))
        self.save_button.setProperty("role", "primary")
        self.save_button.setToolTip(self.tr("Save (Ctrl+S)"))
        self.save_button.clicked.connect(self.save)
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.setToolTip(self.tr("Discard changes (Esc)"))
        self.cancel_button.clicked.connect(self.cancel)
        self.buttons = QHBoxLayout()
        self.buttons.addWidget(self.error, 1)
        self.buttons.addWidget(self.cancel_button)
        self.buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(scroll, 1)
        layout.addLayout(self.buttons)

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        esc.activated.connect(self.cancel)
        self._update_buttons()

    # -- to implement ----------------------------------------------------------

    def build(self, form: FormBuilder) -> None:
        raise NotImplementedError

    def populate(self, obj: Any) -> None:
        raise NotImplementedError

    def validate(self) -> bool:
        return True

    def apply(self, obj: Any) -> None:
        raise NotImplementedError

    def new_object(self) -> Any:
        raise NotImplementedError

    def heading_for(self, obj: Any, is_new: bool) -> str:
        return ""

    def extra_change_widgets(self) -> list[QWidget]:
        """Widgets outside the focus chain whose changes should mark the form dirty."""
        return []

    def after_save(self, obj: Any, is_new: bool) -> None:
        """Hook run after a successful commit."""

    # -- state -----------------------------------------------------------------

    @property
    def dirty(self) -> bool:
        return self._dirty

    def is_new(self) -> bool:
        return self.obj is not None and self.obj.id is None

    def _mark_dirty(self, *_: Any) -> None:
        if not self._loading and not self._dirty:
            self._dirty = True
            self._update_buttons()
            self.dirtyChanged.emit(True)

    def set_clean(self) -> None:
        self._dirty = False
        self._update_buttons()
        self.dirtyChanged.emit(False)

    def _update_buttons(self) -> None:
        has = self.obj is not None
        self.save_button.setEnabled(has and (self._dirty or self.is_new()))
        self.cancel_button.setEnabled(has and (self._dirty or self.is_new()))

    def load(self, obj: Any | None) -> None:
        """Show ``obj``; ``None`` starts a new record."""
        self._loading = True
        try:
            self.obj = obj if obj is not None else self.new_object()
            self.error.hide()
            self.populate(self.obj)
            self.heading.setText(self.heading_for(self.obj, self.is_new()))
        finally:
            self._loading = False
        self.setEnabled(True)
        self.set_clean()

    def clear(self) -> None:
        self.obj = None
        self.heading.setText("")
        self.setEnabled(False)
        self.set_clean()

    def focus_first(self) -> None:
        if self.focus_chain:
            self.focus_chain[0].setFocus()

    # -- actions ---------------------------------------------------------------

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def save(self) -> bool:
        if self.obj is None:
            return False
        self.show_error("")
        if not self.validate():
            self.show_error(self.tr("Please fix the highlighted fields."))
            return False
        session = self.ctx.session
        is_new = self.is_new()
        try:
            with session.no_autoflush:
                self.apply(self.obj)
            session.add(self.obj)
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            self.show_error(self.tr("Could not save: a record with these values already exists."))
            self._log(exc)
            return False
        except SQLAlchemyError as exc:
            session.rollback()
            self.show_error(self.tr("Could not save: {0}").format(exc))
            return False
        self.after_save(self.obj, is_new)
        self.heading.setText(self.heading_for(self.obj, False))
        self.set_clean()
        self.saved.emit(self.obj)
        return True

    def cancel(self) -> None:
        if self.obj is None:
            return
        was_new = self.is_new()
        if was_new:
            self.clear()
        else:
            self.load(self.obj)
        self.cancelled.emit()

    def maybe_discard(self) -> bool:
        """Ask before leaving a form with unsaved changes. True → OK to proceed."""
        if not self._dirty:
            return True
        btn = QMessageBox.question(
            self,
            self.tr("Unsaved changes"),
            self.tr("Save your changes first?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if btn == QMessageBox.StandardButton.Save:
            return self.save()
        if btn == QMessageBox.StandardButton.Discard:
            if self.is_new():
                self.clear()
            else:
                self.load(self.obj)
            return True
        return False

    @staticmethod
    def _log(exc: Exception) -> None:
        import logging

        logging.getLogger(__name__).warning("save failed: %s", exc)
