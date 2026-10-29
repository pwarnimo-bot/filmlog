"""Light / Dark / Darkroom / system theme handling."""

from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

_original_style: str | None = None


def _palette(colors: dict[QPalette.ColorRole, str], disabled_text: str) -> QPalette:
    pal = QPalette()
    for role, value in colors.items():
        pal.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(disabled_text))
    return pal


R = QPalette.ColorRole

LIGHT = {
    R.Window: "#f4f4f2",
    R.WindowText: "#1d1d1d",
    R.Base: "#ffffff",
    R.AlternateBase: "#f0f0ee",
    R.Text: "#1d1d1d",
    R.Button: "#ececea",
    R.ButtonText: "#1d1d1d",
    R.Highlight: "#3a6ea5",
    R.HighlightedText: "#ffffff",
    R.ToolTipBase: "#ffffdc",
    R.ToolTipText: "#1d1d1d",
    R.PlaceholderText: "#8a8a8a",
    R.Link: "#2a5d9f",
    R.Mid: "#c8c8c6",
    R.Dark: "#a0a09e",
}

DARK = {
    R.Window: "#232427",
    R.WindowText: "#e4e4e4",
    R.Base: "#1b1c1e",
    R.AlternateBase: "#26272a",
    R.Text: "#e4e4e4",
    R.Button: "#2e2f33",
    R.ButtonText: "#e4e4e4",
    R.Highlight: "#4f7fb8",
    R.HighlightedText: "#ffffff",
    R.ToolTipBase: "#2e2f33",
    R.ToolTipText: "#e4e4e4",
    R.PlaceholderText: "#7c7c7c",
    R.Link: "#7fb0ec",
    R.Mid: "#3a3b3f",
    R.Dark: "#151618",
}

DARKROOM = {
    R.Window: "#000000",
    R.WindowText: "#a01818",
    R.Base: "#060000",
    R.AlternateBase: "#0d0101",
    R.Text: "#a01818",
    R.Button: "#120202",
    R.ButtonText: "#a01818",
    R.Highlight: "#3a0505",
    R.HighlightedText: "#d02020",
    R.ToolTipBase: "#120202",
    R.ToolTipText: "#a01818",
    R.PlaceholderText: "#5a0c0c",
    R.Link: "#c02020",
    R.Mid: "#2a0404",
    R.Dark: "#000000",
    R.Light: "#2a0404",
    R.Midlight: "#1a0303",
    R.Shadow: "#000000",
    R.BrightText: "#d02020",
}


def _load_qss(name: str) -> str:
    try:
        return (resources.files("filmlog.resources") / "themes" / f"{name}.qss").read_text(
            encoding="utf-8"
        )
    except (FileNotFoundError, OSError):
        return ""


def system_prefers_dark() -> bool:
    try:
        from PySide6.QtCore import Qt

        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return False


def effective_theme(mode: str) -> str:
    """Resolve "system" into "light" or "dark"."""
    if mode == "system":
        return "dark" if system_prefers_dark() else "light"
    return mode


def apply_theme(app: QApplication, mode: str) -> None:
    global _original_style
    if _original_style is None:
        _original_style = app.style().name()

    base_qss = _load_qss("base")
    if mode == "system":
        # Native look: platform style and palette (follows KDE/GNOME settings).
        style = QStyleFactory.create(_original_style)
        if style is not None:
            app.setStyle(style)
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet(base_qss)
        app.setProperty("filmlog_theme", effective_theme("system"))
        return

    app.setStyle(QStyleFactory.create("Fusion"))
    if mode == "dark":
        app.setPalette(_palette(DARK, "#6c6c6c"))
        app.setStyleSheet(base_qss)
    elif mode == "darkroom":
        app.setPalette(_palette(DARKROOM, "#4a0a0a"))
        app.setStyleSheet(base_qss + "\n" + _load_qss("darkroom"))
    else:
        app.setPalette(_palette(LIGHT, "#9a9a9a"))
        app.setStyleSheet(base_qss)
    app.setProperty("filmlog_theme", mode)


def current_theme() -> str:
    app = QApplication.instance()
    value = app.property("filmlog_theme") if app is not None else None
    return str(value) if value else "light"
