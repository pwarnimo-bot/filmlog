# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox
from pytest import MonkeyPatch
from sqlalchemy import select

from filmlog.db.enums import RollStatus
from filmlog.db.models import Development, Print, Roll
from filmlog.ui.main_window import MainWindow
from filmlog.ui.rolls_view import RollsView
from tests.factories import chem, film, make_dev, make_roll


def _rolls_view(win: MainWindow) -> RollsView:
    win.show_view(0)
    view = win.current_view()
    assert isinstance(view, RollsView)
    return view


def test_new_roll_suggests_code_and_calculates_push(main_window: MainWindow) -> None:
    view = _rolls_view(main_window)
    s = view.panel.ctx.session
    view.new_item()
    form = view.panel.roll_form
    assert form.code.text().endswith("-001")
    hp5 = film(s, "HP5 Plus")
    form.film.set_current_id(hp5.id)
    form._film_changed()
    assert form.ei.value() == 400
    assert form.badge.text() == "Box speed"
    form.ei.setValue(1600)
    assert form.stops.value() == 2.0
    assert form.badge.text() == "Push +2"
    form.stops.setValue(1.67)  # user override
    assert form.badge.text() == "Push +1⅔"
    assert form.save()
    roll = s.scalar(select(Roll))
    assert roll is not None
    assert roll.shot_iso == 1600 and roll.push_pull_stops == 1.67
    assert view.panel.table.source.rowCount() == 1


def test_duplicate_code_is_inline_error(main_window: MainWindow) -> None:
    view = _rolls_view(main_window)
    s = view.panel.ctx.session
    make_roll(s, "2026-001")
    s.commit()
    view.new_item()
    form = view.panel.roll_form
    form.code.setText("2026-001")
    form.film.set_current_id(film(s, "FP4 Plus").id)
    assert not form.save()
    assert "already" in form.f_code.hint.text()


def test_mark_as_developed_prefills_from_matching_roll(main_window: MainWindow) -> None:
    view = _rolls_view(main_window)
    s = view.panel.ctx.session
    make_roll(s, "2026-001", "FP4 Plus", 125, developed=make_dev(s, 510, "stock"))
    target = make_roll(s, "2026-002", "FP4 Plus", 125)
    target.status = RollStatus.EXPOSED
    s.commit()
    view.refresh()
    view.select_roll(target.id)
    panel = view.panel
    assert panel.current_roll() is target
    assert panel.mark_button.isVisible()
    panel.mark_developed()
    form = panel.dev_tab.form
    assert form.is_new()
    assert "2026-001" in form.prefill_note.text()
    assert form.dev_time.text() == "8:30"
    assert form.developer.current_id() == chem(s, "Ilford", "ID-11").id
    # Past results show the previous roll for this film + developer + dilution.
    panel.dev_tab.toggle_past.setChecked(True)
    assert [d.roll.code for d in panel.dev_tab.past.table.source.items] == ["2026-001"]
    form.dev_time.setText("9:00")
    assert form.save()
    assert target.status == RollStatus.DEVELOPED
    assert target.development is not None and target.development.dev_time_s == 540
    assert not panel.mark_button.isVisible()


def test_cancel_new_development_leaves_roll_unchanged(main_window: MainWindow) -> None:
    view = _rolls_view(main_window)
    s = view.panel.ctx.session
    roll = make_roll(s, "2026-001")
    roll.status = RollStatus.EXPOSED
    s.commit()
    view.refresh()
    view.select_roll(roll.id)
    view.panel.mark_developed()
    view.panel.dev_tab.form.cancel()
    s.commit()
    assert roll.status == RollStatus.EXPOSED
    assert s.scalar(select(Development)) is None


def test_dev_time_required(main_window: MainWindow) -> None:
    view = _rolls_view(main_window)
    s = view.panel.ctx.session
    roll = make_roll(s, "2026-001")
    s.commit()
    view.refresh()
    view.select_roll(roll.id)
    view.panel.mark_developed()
    form = view.panel.dev_tab.form
    form.developer.set_current_id(chem(s, "Kodak", "D-76").id)
    form.dev_time.setText("")
    assert not form.save()
    assert form.f_time.hint.text()
    form.dev_time.setText("1:75")
    assert not form.save()


def test_delete_roll_with_prints_warns(main_window: MainWindow, monkeypatch: MonkeyPatch) -> None:
    view = _rolls_view(main_window)
    s = view.panel.ctx.session
    roll = make_roll(s, "2026-001")
    roll.prints.append(Print(frame="12", title="Bridge"))
    s.commit()
    view.refresh()
    view.select_roll(roll.id)
    seen: list[str] = []

    def fake_warning(parent, title, text, *a, **k):  # type: ignore[no-untyped-def]
        seen.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "warning", fake_warning)
    view.panel.delete_current()
    assert seen and "frame 12" in seen[0] and "Bridge" in seen[0]
    assert s.get(Roll, roll.id) is not None
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    view.panel.delete_current()
    assert s.scalar(select(Roll)) is None
    assert s.scalar(select(Print)) is None
