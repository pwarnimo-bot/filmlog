from __future__ import annotations

from PySide6.QtWidgets import QApplication

from filmlog.ui.main_window import MainWindow
from filmlog.ui.theme import apply_theme


def test_main_window_starts(main_window: MainWindow) -> None:
    win = main_window
    assert win.sidebar.count() == 5
    win.show_view(2)
    assert win.stack.currentIndex() == 2


def test_theme_switching(main_window: MainWindow) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    for mode in ("light", "dark", "darkroom", "system"):
        apply_theme(app, mode)
        assert app.property("filmlog_theme") in ("light", "dark", "darkroom")
