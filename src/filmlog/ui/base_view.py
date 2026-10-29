# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Common interface for the views shown in the main window's stack."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


class BaseView(QWidget):
    """A page in the main window. Keyboard actions are dispatched to these hooks."""

    title: str = ""

    def new_item(self) -> None:  # Ctrl+N
        pass

    def focus_search(self) -> None:  # Ctrl+F
        pass

    def save(self) -> None:  # Ctrl+S
        pass

    def refresh(self) -> None:
        """Reload data (called when the view becomes visible or data changed elsewhere)."""

    def shutdown(self) -> None:
        """Persist view state (column widths etc.) before the app quits."""
