"""Cameras view: table of cameras with detail form and the camera's rolls."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from filmlog.db.enums import CameraStatus, CameraType, FilmFormat
from filmlog.db.models import Camera, Roll
from filmlog.services import cameras as cam_service
from filmlog.ui.base_view import BaseView
from filmlog.ui.catalogue_view import notes_edit
from filmlog.ui.context import AppContext
from filmlog.ui.editor import EditorForm
from filmlog.ui.labels import label
from filmlog.ui.list_detail import ListDetailPanel
from filmlog.ui.table_model import OBJECT_ROLE, Column, ObjectTable
from filmlog.ui.widgets import (
    EnumCombo,
    FormBuilder,
    OptionalDateEdit,
    OptionalDoubleSpin,
    OptionalIntSpin,
)


def _tr(text: str) -> str:
    return QCoreApplication.translate("Cameras", text)


class CameraForm(EditorForm):
    def build(self, form: FormBuilder) -> None:
        self.make = QLineEdit()
        self.model = QLineEdit()
        self.nickname = QLineEdit()
        self.nickname.setPlaceholderText(self.tr("optional, e.g. “the black FM2”"))
        self.type = EnumCombo(CameraType)
        self.format = EnumCombo(FilmFormat)
        self.mount = QLineEdit()
        self.lenses = QPlainTextEdit()
        self.lenses.setTabChangesFocus(True)
        self.lenses.setFixedHeight(64)
        self.lenses.setPlaceholderText(self.tr("One lens per line, e.g. Nikkor 50mm f/1.8 AI-S"))
        self.serial = QLineEdit()
        self.year = OptionalIntSpin(1850, 2100)
        self.shutter = QLineEdit()
        self.shutter.setPlaceholderText(self.tr("e.g. mechanical, 1 s–1/4000 s, B"))
        self.metering = QLineEdit()
        self.metering.setPlaceholderText(self.tr("e.g. TTL centre-weighted, or none"))
        self.battery = QLineEdit()
        self.acquired = OptionalDateEdit()
        self.price = OptionalDoubleSpin(0, 1_000_000, 2)
        self.status = EnumCombo(CameraStatus)
        self.notes = notes_edit()

        self.f_make = form.add(self.tr("Make"), self.make)
        self.f_model = form.add(self.tr("Model"), self.model)
        form.add(self.tr("Nickname"), self.nickname)
        form.add(self.tr("Type"), self.type)
        form.add(self.tr("Format"), self.format)
        form.add(self.tr("Lens mount"), self.mount)
        form.add(self.tr("Lenses"), self.lenses)
        form.add(self.tr("Status"), self.status)
        form.section(self.tr("Details"))
        form.add(self.tr("Shutter"), self.shutter)
        form.add(self.tr("Metering"), self.metering)
        form.add(self.tr("Battery"), self.battery)
        form.add(self.tr("Serial number"), self.serial)
        form.add(self.tr("Year made"), self.year)
        form.add(self.tr("Acquired"), self.acquired)
        form.add(self.tr("Price paid"), self.price)
        form.add(self.tr("Notes"), self.notes)

    def new_object(self) -> Camera:
        return Camera(make="", model="", camera_type=CameraType.SLR, format=FilmFormat.F135,
                      status=CameraStatus.ACTIVE)  # fmt: skip

    def heading_for(self, obj: Camera, is_new: bool) -> str:
        return self.tr("New camera") if is_new else obj.display_name

    def populate(self, obj: Camera) -> None:
        self.make.setText(obj.make or "")
        self.model.setText(obj.model or "")
        self.nickname.setText(obj.nickname or "")
        self.type.set_value(obj.camera_type)
        self.format.set_value(obj.format)
        self.mount.setText(obj.lens_mount or "")
        self.lenses.setPlainText(obj.lenses or "")
        self.serial.setText(obj.serial_number or "")
        self.year.set_value(obj.year_made)
        self.shutter.setText(obj.shutter or "")
        self.metering.setText(obj.metering or "")
        self.battery.setText(obj.battery or "")
        self.acquired.set_value(obj.acquired_date)
        self.price.set_value(obj.acquired_price)
        self.status.set_value(obj.status)
        self.notes.setPlainText(obj.notes or "")

    def validate(self) -> bool:
        ok = self.f_make.set_error(
            None if self.make.text().strip() else self.tr("Make is required.")
        )
        ok = (
            self.f_model.set_error(
                None if self.model.text().strip() else self.tr("Model is required.")
            )
            and ok
        )
        return ok

    def apply(self, obj: Camera) -> None:
        obj.make = self.make.text().strip()
        obj.model = self.model.text().strip()
        obj.nickname = self.nickname.text().strip()
        obj.camera_type = self.type.value()
        obj.format = self.format.value()
        obj.lens_mount = self.mount.text().strip()
        obj.lenses = self.lenses.toPlainText().strip()
        obj.serial_number = self.serial.text().strip()
        obj.year_made = self.year.value_or_none()
        obj.shutter = self.shutter.text().strip()
        obj.metering = self.metering.text().strip()
        obj.battery = self.battery.text().strip()
        obj.acquired_date = self.acquired.value()
        obj.acquired_price = self.price.value_or_none()
        obj.status = self.status.value()
        obj.notes = self.notes.toPlainText()


class CamerasPanel(ListDetailPanel):
    openRoll = Signal(int)  # noqa: N815

    def __init__(self, ctx: AppContext) -> None:
        self._counts: dict[int, int] = {}
        cols = [
            Column(_tr("Name"), lambda c: c.display_name, width=170),
            Column(_tr("Make / model"), lambda c: f"{c.make} {c.model}", width=170),
            Column(_tr("Type"), lambda c: label(c.camera_type), width=120),
            Column(_tr("Format"), lambda c: label(c.format), width=80),
            Column(_tr("Mount"), lambda c: c.lens_mount, width=110),
            Column(_tr("Status"), lambda c: label(c.status), width=70),
            Column(_tr("Rolls"), lambda c: self._counts.get(c.id, 0), align_right=True, width=50),
        ]
        self.rolls_label = QLabel()
        super().__init__(ctx, "cameras", cols, CameraForm(ctx), new_label=_tr("New camera"))
        self.table.source.dimmed = lambda c: c.status != CameraStatus.ACTIVE
        self.editor.saved.connect(lambda _: self._load_rolls())

    def detail_widget(self) -> QWidget:
        self.rolls = ObjectTable(
            "camera_rolls",
            [
                Column(_tr("Code"), lambda r: r.code, width=90),
                Column(_tr("Title"), lambda r: r.title, width=160),
                Column(_tr("Film"), lambda r: r.film_stock.display_name, width=170),
                Column(_tr("Status"), lambda r: label(r.status), width=80),
            ],
            self.ctx.settings,
        )
        self.rolls.setToolTip(_tr("Double-click to open the roll"))
        self.rolls.doubleClicked.connect(self._open_roll)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.rolls_label)
        v.addWidget(self.rolls)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.editor)
        split.addWidget(box)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        return split

    def fetch(self) -> Sequence[Camera]:
        self._counts = cam_service.roll_counts(self.ctx.session)
        return cam_service.list_cameras(self.ctx.session)

    def _on_current(self, *args: object) -> None:
        super()._on_current(*args)
        self._load_rolls()

    def refresh(self, select: object = None) -> None:
        super().refresh(select)
        self._load_rolls()

    def _load_rolls(self) -> None:
        cam = self.editor.obj
        rolls: Sequence[Roll] = []
        if isinstance(cam, Camera) and cam.id is not None:
            rolls = cam_service.rolls_for(self.ctx.session, cam.id)
        self.rolls.set_items(rolls)
        self.rolls_label.setText(_tr("<b>Rolls shot with this camera</b> ({0})").format(len(rolls)))

    def _open_roll(self, index: QModelIndex) -> None:
        roll = self.rolls.proxy.mapToSource(index).data(OBJECT_ROLE)
        if roll is not None:
            self.openRoll.emit(roll.id)

    def confirm_delete(self, obj: object) -> bool:
        assert isinstance(obj, Camera)
        n = self._counts.get(obj.id, 0)
        if n:
            btn = QMessageBox.question(
                self,
                _tr("Delete camera"),
                _tr(
                    "“{0}” was used for {1} roll(s). Those rolls will keep their data but "
                    "lose the camera link.\n\nConsider setting the status to Retired or Sold "
                    "instead. Delete anyway?"
                ).format(obj.display_name, n),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return btn == QMessageBox.StandardButton.Yes
        return super().confirm_delete(obj)

    def shutdown(self) -> None:
        super().shutdown()
        self.rolls.save_state()


class CamerasView(BaseView):
    openRoll = Signal(int)  # noqa: N815

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = self.tr("Cameras")
        self.panel = CamerasPanel(ctx)
        self.panel.openRoll.connect(self.openRoll)
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel)

    def refresh(self) -> None:
        self.panel.refresh()

    def new_item(self) -> None:
        self.panel.new_item()

    def focus_search(self) -> None:
        self.panel.focus_search()

    def save(self) -> None:
        self.panel.save()

    def shutdown(self) -> None:
        self.panel.shutdown()
