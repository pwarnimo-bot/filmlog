# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main window: sidebar navigation + stacked views + menus."""

from __future__ import annotations

import contextlib

from PySide6.QtCore import QByteArray, QSize
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from filmlog import __copyright__, __version__
from filmlog.ui import file_actions as fa
from filmlog.ui.base_view import BaseView
from filmlog.ui.cameras_view import CamerasView
from filmlog.ui.catalogue_view import CatalogueView
from filmlog.ui.context import AppContext
from filmlog.ui.prints_view import PrintsView
from filmlog.ui.rolls_view import RollsView
from filmlog.ui.settings_dialog import SettingsDialog
from filmlog.ui.statistics_view import StatisticsView
from filmlog.ui.theme import apply_theme
from filmlog.ui.widgets import fit_to_screen


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(self.tr("FilmLog"))
        fit_to_screen(self, 1400, 860, margin=0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(136)
        self.sidebar.setIconSize(QSize(20, 20))
        self.stack = QStackedWidget()

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.views: list[BaseView] = []
        for view in self._build_views():
            self._add_view(view)

        self.sidebar.currentRowChanged.connect(self._on_nav)
        with contextlib.suppress(AttributeError):  # Qt < 6.5 has no colorSchemeChanged
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        self._build_menus()
        self._restore_state()

    # -- views ---------------------------------------------------------------

    def _build_views(self) -> list[BaseView]:
        return [
            RollsView(self.ctx),
            self._prints_view(),
            self._cameras_view(),
            CatalogueView(self.ctx),
            StatisticsView(self.ctx),
        ]

    def _prints_view(self) -> BaseView:
        view = PrintsView(self.ctx)
        view.openRoll.connect(self.open_roll)
        return view

    def _cameras_view(self) -> BaseView:
        view = CamerasView(self.ctx)
        view.openRoll.connect(self.open_roll)
        return view

    def open_roll(self, roll_id: int) -> None:
        """Navigate to the Rolls view and select a roll."""
        self.show_view(0)
        view = self.views[0]
        if isinstance(view, RollsView):
            view.select_roll(roll_id)

    def _add_view(self, view: BaseView) -> None:
        self.views.append(view)
        self.stack.addWidget(view)
        QListWidgetItem(view.title, self.sidebar)

    def current_view(self) -> BaseView:
        return self.views[self.stack.currentIndex()]

    def show_view(self, index: int) -> None:
        self.sidebar.setCurrentRow(index)

    def _on_nav(self, row: int) -> None:
        if 0 <= row < len(self.views):
            self.stack.setCurrentIndex(row)
            self.views[row].refresh()

    # -- menus & shortcuts ---------------------------------------------------

    def _build_menus(self) -> None:
        bar = self.menuBar()
        self.file_menu = bar.addMenu(self.tr("&File"))
        self.edit_menu = bar.addMenu(self.tr("&Edit"))
        self.help_menu = bar.addMenu(self.tr("&Help"))

        new = QAction(self.tr("&New"), self)
        new.setShortcut(QKeySequence.StandardKey.New)
        new.triggered.connect(lambda: self.current_view().new_item())
        find = QAction(self.tr("&Find"), self)
        find.setShortcut(QKeySequence.StandardKey.Find)
        find.triggered.connect(lambda: self.current_view().focus_search())
        save = QAction(self.tr("&Save"), self)
        save.setShortcut(QKeySequence.StandardKey.Save)
        save.triggered.connect(lambda: self.current_view().save())
        for a in (new, find, save):
            self.edit_menu.addAction(a)
        self.edit_menu.addSeparator()
        prefs = QAction(self.tr("Se&ttings…"), self)
        prefs.setShortcut(QKeySequence("Ctrl+,"))
        prefs.triggered.connect(self.open_settings)
        self.edit_menu.addAction(prefs)

        fm = self.file_menu
        fm.addAction(self.tr("Export to &CSV (zip)…"), lambda: fa.export_csv(self, self.ctx))
        fm.addAction(self.tr("Export to &JSON…"), lambda: fa.export_full_json(self, self.ctx))
        fm.addAction(self.tr("&Import JSON…"), self._import_json)
        fm.addSeparator()
        card = QAction(self.tr("Export roll as darkroom card (&PDF)…"), self)
        card.setShortcut(QKeySequence("Ctrl+P"))
        card.triggered.connect(self._export_card)
        fm.addAction(card)
        fm.addSeparator()
        fm.addAction(self.tr("&Back up database now…"), lambda: fa.backup_now(self, self.ctx))
        fm.addSeparator()
        quit_ = QAction(self.tr("&Quit"), self)
        quit_.setShortcut(QKeySequence.StandardKey.Quit)
        quit_.triggered.connect(self.close)
        fm.addAction(quit_)

        hm = self.help_menu
        hm.addAction(self.tr("Load &demo data"), self._load_demo)
        hm.addAction(self.tr("&Remove demo data"), self._remove_demo)
        hm.addSeparator()
        about = QAction(self.tr("&About FilmLog"), self)
        about.triggered.connect(self._about)
        hm.addAction(about)

        # Ctrl+1..5 jump to sidebar entries.
        for i in range(len(self.views)):
            act = QAction(self)
            act.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            act.triggered.connect(lambda _=False, i=i: self.show_view(i))
            self.addAction(act)

    def _system_scheme_changed(self, *_: object) -> None:
        """The desktop switched light/dark: follow it when the theme is "system"."""
        app = QApplication.instance()
        if self.ctx.settings.theme == "system" and isinstance(app, QApplication):
            apply_theme(app, "system")
            self.refresh_all()

    def refresh_all(self) -> None:
        for v in self.views:
            v.refresh()

    def _import_json(self) -> None:
        if fa.import_full_json(self, self.ctx):
            self.refresh_all()

    def _load_demo(self) -> None:
        if fa.load_demo(self, self.ctx):
            self.refresh_all()

    def _remove_demo(self) -> None:
        if fa.remove_demo(self, self.ctx):
            self.refresh_all()

    def _export_card(self) -> None:
        view = self.views[0]
        roll = view.panel.current_roll() if isinstance(view, RollsView) else None
        fa.export_card(self, self.ctx, roll)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.ctx.settings, self)
        if dlg.exec():
            dlg.apply_to(self.ctx.settings)
            self.ctx.settings.save()
            app = QApplication.instance()
            if isinstance(app, QApplication):
                apply_theme(app, self.ctx.settings.theme)
            for v in self.views:
                v.refresh()

    def _about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("About FilmLog"),
            self.tr(
                "<h3>FilmLog {0}</h3>"
                "<p>Darkroom film &amp; print manager.</p>"
                "<p>{1} — written by Pol Warnimont, developed with the help of "
                "Claude (Anthropic).</p>"
                "<p>This program is free software: you can redistribute it and/or modify "
                "it under the terms of the GNU General Public License, version 3 or "
                "(at your option) any later version. It comes with ABSOLUTELY NO "
                "WARRANTY.</p>"
            ).format(__version__, __copyright__),
        )

    # -- state ---------------------------------------------------------------

    def _restore_state(self) -> None:
        s = self.ctx.settings
        if s.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode()))
        if s.window_state:
            self.restoreState(QByteArray.fromBase64(s.window_state.encode()))
        index = s.last_view if 0 <= s.last_view < len(self.views) else 0
        self.sidebar.setCurrentRow(index)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        s = self.ctx.settings
        s.window_geometry = bytes(self.saveGeometry().toBase64().data()).decode()
        s.window_state = bytes(self.saveState().toBase64().data()).decode()
        s.last_view = self.stack.currentIndex()
        for v in self.views:
            v.shutdown()
        with contextlib.suppress(OSError):
            s.save()
        event.accept()
