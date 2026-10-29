# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Settings dialog: theme and units."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from filmlog.services.settings import Settings


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))
        self._settings = settings

        self.theme = QComboBox()
        for key, label in (
            ("system", self.tr("Follow system (colours, light/dark)")),
            ("light", self.tr("Light")),
            ("dark", self.tr("Dark")),
            ("darkroom", self.tr("Darkroom (red on black)")),
        ):
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))

        self.temp = QComboBox()
        self.temp.addItem(self.tr("Celsius (°C)"), "C")
        self.temp.addItem(self.tr("Fahrenheit (°F)"), "F")
        self.temp.setCurrentIndex(max(0, self.temp.findData(settings.temperature_unit)))

        self.length = QComboBox()
        self.length.addItem(self.tr("Centimetres (cm)"), "cm")
        self.length.addItem(self.tr("Inches (in)"), "in")
        self.length.setCurrentIndex(max(0, self.length.findData(settings.length_unit)))

        form = QFormLayout()
        form.addRow(self.tr("Theme"), self.theme)
        form.addRow(self.tr("Temperature"), self.temp)
        form.addRow(self.tr("Lengths"), self.length)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def apply_to(self, settings: Settings) -> None:
        settings.theme = str(self.theme.currentData())
        settings.temperature_unit = str(self.temp.currentData())
        settings.length_unit = str(self.length.currentData())
