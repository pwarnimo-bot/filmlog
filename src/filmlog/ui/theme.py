# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Light / Dark / Darkroom / system theme handling."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from importlib import resources

from PySide6.QtCore import Qt
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


# Desktops for which Qt already loads a matching platform theme on its own.
_QT_HANDLED_DESKTOPS = {
    "KDE", "LXQT", "GNOME", "UNITY", "X-CINNAMON", "CINNAMON", "MATE", "XFCE", "LXDE",
    "BUDGIE", "PANTHEON", "DEEPIN",
}  # fmt: skip
QT_DEFAULT_HIGHLIGHT = "#308cc6"  # Qt's built-in highlight when no desktop theme is loaded

_system_accent: QColor | None = None

# Inline error hints need a lighter red to stay readable on dark backgrounds.
DARK_HINTS = '\nQLabel[hint="true"] { color: #ff7b72; }\n'


def platform_theme_for(env: Mapping[str, str], platform: str = sys.platform) -> str | None:
    """Qt platform theme to request so the system colours are used, or None.

    On desktops Qt doesn't recognise (Sway, Hyprland, i3, niri, …) Qt falls back to
    plain Fusion colours. Those setups usually configure their look through GTK
    settings, so we ask Qt for its GTK 3 theme, which reads the GTK theme, its
    colours and the dark/light preference. An explicit QT_QPA_PLATFORMTHEME wins.
    """
    if not platform.startswith(("linux", "freebsd", "openbsd", "netbsd")):
        return None
    if env.get("QT_QPA_PLATFORMTHEME"):
        return None
    desktops = {d.strip().upper() for d in env.get("XDG_CURRENT_DESKTOP", "").split(":")}
    if desktops & _QT_HANDLED_DESKTOPS:
        return None
    return "gtk3"


def configure_platform_theme() -> None:
    """Call before creating the QApplication."""
    theme = platform_theme_for(os.environ)
    if theme:
        os.environ["QT_QPA_PLATFORMTHEME"] = theme


def system_prefers_dark() -> bool:
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except AttributeError:  # Qt < 6.5
        pass
    # Unknown: judge by the system palette's window colour.
    return QPalette().color(QPalette.ColorRole.Window).lightness() < 128


def effective_theme(mode: str) -> str:
    """Resolve "system" into "light" or "dark"."""
    if mode == "system":
        return "dark" if system_prefers_dark() else "light"
    return mode


def system_accent() -> QColor | None:
    """The desktop's highlight colour, if the platform theme provides one."""
    return _system_accent


def _capture_system_accent(app: QApplication) -> None:
    global _system_accent
    if _system_accent is None:
        c = app.palette().color(QPalette.ColorRole.Highlight)
        _system_accent = c if c.name() != QT_DEFAULT_HIGHLIGHT else QColor()


def _with_accent(pal: QPalette) -> QPalette:
    accent = _system_accent
    if accent is not None and accent.isValid():
        pal.setColor(QPalette.ColorRole.Highlight, accent)
        pal.setColor(QPalette.ColorRole.Accent, accent)
        text = "#000000" if accent.lightness() > 150 else "#ffffff"
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(text))
    return pal


def apply_theme(app: QApplication, mode: str) -> None:
    global _original_style
    if _original_style is None:
        _original_style = app.style().name()
        _capture_system_accent(app)

    base_qss = _load_qss("base")
    if mode == "system":
        # Desktop style and palette: colours and light/dark come from the system.
        style = QStyleFactory.create(_original_style)
        if style is not None:
            app.setStyle(style)
        app.setPalette(QPalette())  # an empty palette restores the platform palette
        effective = effective_theme("system")
        app.setStyleSheet(base_qss + (DARK_HINTS if effective == "dark" else ""))
        app.setProperty("filmlog_theme", effective)
        return

    app.setStyle(QStyleFactory.create("Fusion"))
    if mode == "dark":
        app.setPalette(_with_accent(_palette(DARK, "#6c6c6c")))
        app.setStyleSheet(base_qss + DARK_HINTS)
    elif mode == "darkroom":
        app.setPalette(_palette(DARKROOM, "#4a0a0a"))
        app.setStyleSheet(base_qss + "\n" + _load_qss("darkroom"))
    else:
        app.setPalette(_with_accent(_palette(LIGHT, "#9a9a9a")))
        app.setStyleSheet(base_qss)
    app.setProperty("filmlog_theme", mode)


def accent_colour() -> QColor:
    """Colour for charts and similar accents in the current theme."""
    if current_theme() == "darkroom":
        return QColor("#8a1010")
    return QGuiApplication.palette().color(QPalette.ColorRole.Highlight)


def current_theme() -> str:
    app = QApplication.instance()
    value = app.property("filmlog_theme") if app is not None else None
    return str(value) if value else "light"
