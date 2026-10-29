from __future__ import annotations

from pytestqt.qtbot import QtBot

from filmlog.app import build_main_window, create_app
from filmlog.ui.theme import apply_theme


def test_main_window_starts(qtbot: QtBot) -> None:
    app = create_app([])
    win = build_main_window(app)
    qtbot.addWidget(win)
    win.show()
    assert win.sidebar.count() == 5
    win.show_view(2)
    assert win.stack.currentIndex() == 2


def test_theme_switching(qtbot: QtBot) -> None:
    app = create_app([])
    for mode in ("light", "dark", "darkroom", "system"):
        apply_theme(app, mode)
