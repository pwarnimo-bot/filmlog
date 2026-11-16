# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cameras tab."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from filmlog.db.enums import CameraStatus, CameraType, FilmFormat
from filmlog.db.models import Camera
from filmlog.services import cameras as camera_service
from filmlog.services import records
from filmlog.tui.forms import ConfirmScreen, Field, FormScreen
from filmlog.tui.listpane import Col, ListPane
from filmlog.tui.options import enum_options, label

CAMERA_FIELDS = [
    Field("make", "Make", required=True),
    Field("model", "Model", required=True),
    Field("nickname", "Nickname", placeholder="optional, e.g. the black FM2"),
    Field("camera_type", "Type", "select", enum_options(CameraType), allow_blank=False),
    Field("format", "Format", "select", enum_options(FilmFormat), allow_blank=False),
    Field("lens_mount", "Lens mount"),
    Field("lenses", "Lenses", "area", placeholder="Lenses owned for this body, one per line"),
    Field("status", "Status", "select", enum_options(CameraStatus), allow_blank=False),
    Field("details", "Details", "section"),
    Field("serial_number", "Serial number"),
    Field("year_made", "Year made", "int"),
    Field("shutter", "Shutter", placeholder="e.g. mechanical, 1 s–1/4000 s, B"),
    Field("metering", "Metering", placeholder="e.g. TTL centre-weighted, or none"),
    Field("battery", "Battery"),
    Field("acquired_date", "Acquired", "date"),
    Field("acquired_price", "Price paid", "float"),
    Field("notes", "Notes", "area"),
]
_KEYS = [f.key for f in CAMERA_FIELDS if f.kind != "section"]


class CamerasPane(ListPane):
    new_label = "New camera"
    empty_text = "No cameras yet — ctrl+n adds one"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._counts: dict[int, int] = {}
        self.columns = [
            Col("Name", lambda c: c.display_name, width=24),
            Col("Make / model", lambda c: f"{c.make} {c.model}", width=24),
            Col("Type", lambda c: label(c.camera_type), width=18),
            Col("Format", lambda c: label(c.format), width=9),
            Col("Mount", lambda c: c.lens_mount, width=16),
            Col("Status", lambda c: label(c.status), width=8),
            Col(
                "Rolls",
                lambda c: self._counts.get(c.id, 0),
                sort=lambda c: self._counts.get(c.id, 0),
                right=True,
                width=5,
            ),
        ]

    def fetch(self) -> Sequence[Any]:
        self._counts = camera_service.roll_counts(self.session)
        return camera_service.list_cameras(self.session)

    def item_dimmed(self, obj: Any) -> bool:
        return bool(obj.status != CameraStatus.ACTIVE)

    def _form(self, cam: Camera) -> None:
        is_new = cam.id is None
        values = {k: getattr(cam, k) for k in _KEYS}
        note = ""
        if not is_new:
            rolls = camera_service.rolls_for(self.session, cam.id)
            if rolls:
                codes = ", ".join(r.code for r in rolls[:12]) + (" …" if len(rolls) > 12 else "")
                note = f"Rolls shot with this camera ({len(rolls)}): {codes}"

        def done(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            for k, v in result.items():
                setattr(cam, k, v)
            self.session.add(cam)
            self.session.commit()
            self.tui.data_changed(select=cam)
            self.app.notify(f"Saved {cam.display_name}.")

        self.app.push_screen(
            FormScreen(
                "New camera" if is_new else f"Camera — {cam.display_name}",
                CAMERA_FIELDS,
                values,
                note=note,
            ),
            done,
        )

    def new_item(self) -> None:
        self._form(
            Camera(
                make="",
                model="",
                camera_type=CameraType.SLR,
                format=FilmFormat.F135,
                status=CameraStatus.ACTIVE,
                notes="",
            )
        )

    def open_item(self, obj: Any) -> None:
        self._form(obj)

    def delete_item(self, obj: Any) -> None:
        def answer(ok: bool | None) -> None:
            if ok:
                records.delete_camera(self.session, obj)
                self.tui.data_changed()
                self.app.notify("Camera deleted.")

        self.app.push_screen(
            ConfirmScreen(records.camera_delete_question(self.session, obj), yes="Delete"), answer
        )
