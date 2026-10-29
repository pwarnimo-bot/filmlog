# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from sqlalchemy import select

from filmlog.db.models import Camera, FilmStock
from filmlog.ui.cameras_view import CamerasView
from filmlog.ui.catalogue_view import CatalogueView, FilmsPanel
from filmlog.ui.main_window import MainWindow
from tests.factories import make_roll


def test_create_camera_with_validation(main_window: MainWindow) -> None:
    win = main_window
    win.show_view(2)
    view = win.current_view()
    assert isinstance(view, CamerasView)
    view.new_item()
    form = view.panel.editor
    assert not form.save()  # make/model required
    assert form.f_make.hint.text()
    form.make.setText("Nikon")
    form.model.setText("FM2")
    form.nickname.setText("the black FM2")
    assert form.save()
    cams = win.ctx.session.scalars(select(Camera)).all()
    assert [c.display_name for c in cams] == ["the black FM2"]
    assert view.panel.table.source.rowCount() == 1


def test_catalogue_lists_seed_and_blocks_delete_in_use(
    main_window: MainWindow, monkeypatch: MonkeyPatch
) -> None:
    win = main_window
    win.show_view(3)
    view = win.current_view()
    assert isinstance(view, CatalogueView)
    panel = view.panels[0]
    assert isinstance(panel, FilmsPanel)
    assert panel.table.source.rowCount() == 33
    s = win.ctx.session
    make_roll(s, "2026-001", "FP4 Plus")
    s.commit()
    fp4 = s.scalar(select(FilmStock).where(FilmStock.name == "FP4 Plus"))
    panel.refresh(select=fp4)
    assert panel.table.current_object() is fp4
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    panel.delete_current()
    assert fp4 is not None and fp4.discontinued  # offered "mark discontinued" instead
    assert s.get(FilmStock, fp4.id) is not None


def test_chemical_kind_filter(main_window: MainWindow) -> None:
    win = main_window
    win.show_view(3)
    view = win.current_view()
    assert isinstance(view, CatalogueView)
    view.tabs.setCurrentIndex(1)
    chem = view.panels[1]
    total = chem.table.proxy.rowCount()
    chem.kind_filter.setCurrentIndex(chem.kind_filter.findData("stop_bath"))  # type: ignore[attr-defined]
    assert 0 < chem.table.proxy.rowCount() < total
