# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

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


def test_platform_theme_choice() -> None:
    from filmlog.ui.theme import platform_theme_for

    assert platform_theme_for({"XDG_CURRENT_DESKTOP": "sway:wlroots"}, "linux") == "gtk3"
    assert platform_theme_for({"XDG_CURRENT_DESKTOP": "Hyprland"}, "linux") == "gtk3"
    assert platform_theme_for({}, "linux") == "gtk3"
    assert platform_theme_for({"XDG_CURRENT_DESKTOP": "KDE"}, "linux") is None
    assert platform_theme_for({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, "linux") is None
    explicit = {"XDG_CURRENT_DESKTOP": "sway", "QT_QPA_PLATFORMTHEME": "qt6ct"}
    assert platform_theme_for(explicit, "linux") is None
    assert platform_theme_for({}, "win32") is None


def test_system_theme_restores_platform_palette(main_window: MainWindow) -> None:
    from PySide6.QtGui import QPalette

    from filmlog.ui.theme import current_theme

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    platform_window = QPalette().color(QPalette.ColorRole.Window).name()
    apply_theme(app, "darkroom")
    assert app.palette().color(QPalette.ColorRole.Window).name() == "#000000"
    apply_theme(app, "system")
    assert app.palette().color(QPalette.ColorRole.Window).name() == platform_window
    assert current_theme() in ("light", "dark")


def test_light_and_dark_use_system_accent(main_window: MainWindow) -> None:
    from PySide6.QtGui import QColor, QPalette

    from filmlog.ui import theme

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    saved = theme._system_accent
    try:
        theme._system_accent = QColor("#307d80")
        for mode in ("light", "dark"):
            apply_theme(app, mode)
            assert app.palette().color(QPalette.ColorRole.Highlight).name() == "#307d80"
        apply_theme(app, "darkroom")  # darkroom keeps its own red palette
        assert app.palette().color(QPalette.ColorRole.Highlight).name() == "#3a0505"
    finally:
        theme._system_accent = saved
        apply_theme(app, "system")


def test_fits_1366x768_laptop_screen(main_window: MainWindow) -> None:
    """Every view must fit a 1366×768 screen (minus a panel/bar of ~40 px)."""
    from filmlog.services import demo

    demo.load_demo(main_window.ctx.session)
    main_window.refresh_all()
    for i in range(len(main_window.views)):
        main_window.show_view(i)
        hint = main_window.minimumSizeHint()
        assert hint.width() <= 1366 and hint.height() <= 728, (i, hint)


def test_dialogs_fit_screen(main_window: MainWindow) -> None:
    from filmlog.ui.print_form import PrintDialog

    dlg = PrintDialog(main_window.ctx, main_window)
    avail = dlg.screen().availableGeometry()
    assert dlg.width() <= avail.width() and dlg.height() <= avail.height()
    dlg.deleteLater()
