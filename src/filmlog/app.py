"""QApplication setup: theme, main window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from filmlog import paths
from filmlog.db.database import open_database
from filmlog.services.settings import Settings
from filmlog.ui.context import AppContext
from filmlog.ui.main_window import MainWindow
from filmlog.ui.theme import apply_theme


def create_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("FilmLog")
    app.setOrganizationName("filmlog")
    app.setDesktopFileName("filmlog")
    return app


def build_main_window(app: QApplication) -> MainWindow:
    paths.ensure_dirs()
    settings = Settings.load()
    apply_theme(app, settings.theme)
    db = open_database(paths.db_path(), paths.backups_dir())
    ctx = AppContext(settings=settings, db=db)
    return MainWindow(ctx)


def run(argv: list[str] | None = None) -> int:
    app = create_app(argv)
    window = build_main_window(app)
    window.show()
    return app.exec()
