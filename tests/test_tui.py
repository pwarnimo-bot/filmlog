# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Full-screen terminal app, driven headlessly with Textual's pilot."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from textual.pilot import Pilot
from textual.widgets import Input

from filmlog.db.enums import RollStatus
from filmlog.db.models import Camera, FilmStock, Print, Roll
from filmlog.services.demo import load_demo
from filmlog.services.settings import Settings
from filmlog.tui.app import FilmLogTUI, MainScreen
from filmlog.tui.cameras import CamerasPane
from filmlog.tui.catalogue import FilmsPane
from filmlog.tui.forms import ConfirmScreen, FormScreen
from filmlog.tui.prints import ExposureEditor
from filmlog.tui.rolls import RollScreen, RollsPane

Scenario = Callable[[FilmLogTUI, Pilot[None]], Awaitable[None]]


def run(db: Any, scenario: Scenario, *, demo: bool = True) -> None:
    if demo:
        with db.session() as s:
            load_demo(s)

    async def main() -> None:
        app = FilmLogTUI(db, Settings())
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            await scenario(app, pilot)

    asyncio.run(main())


def form(app: FilmLogTUI) -> FormScreen:
    assert isinstance(app.screen, FormScreen), app.screen
    return app.screen


def test_single_click_opens_roll_and_escape_returns(db: Any) -> None:
    async def scenario(app: FilmLogTUI, pilot: Pilot[None]) -> None:
        pane = app.screen.query_one(RollsPane)
        assert pane.table.row_count == 9
        await pilot.click(pane.table, offset=(3, 2))  # second data row: 2026-008
        await pilot.pause()
        assert isinstance(app.screen, RollScreen)
        assert app.screen.roll.code == "2026-008"
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)

    run(db, scenario)


def test_mark_as_developed_prefills_and_validates(db: Any) -> None:
    async def scenario(app: FilmLogTUI, pilot: Pilot[None]) -> None:
        roll = app.session.scalar(select(Roll).where(Roll.code == "2026-008"))
        assert roll is not None
        await app.push_screen(RollScreen(roll))
        await pilot.press("m")
        await pilot.pause()
        f = form(app)
        assert "Pre-filled from roll" in str(f.query_one("#note").render())
        # Demo roll 2026-007 (the source) has 0:00 — a real time is required.
        f.widget("dev_time_s").value = ""  # type: ignore[attr-defined]
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, FormScreen)
        assert "required" in str(f.query_one("#e-dev_time_s").render())
        f.widget("dev_time_s").value = "9:30"  # type: ignore[attr-defined]
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, RollScreen)
        assert roll.status == RollStatus.DEVELOPED
        assert roll.development is not None and roll.development.dev_time_s == 570

    run(db, scenario)


def test_add_split_grade_print(db: Any) -> None:
    async def scenario(app: FilmLogTUI, pilot: Pilot[None]) -> None:
        roll = app.session.scalar(select(Roll).where(Roll.code == "2026-003"))
        assert roll is not None
        await app.push_screen(RollScreen(roll))
        await pilot.press("p")
        await pilot.pause()
        f = form(app)
        f.widget("contrast_method").value = "split_grade"  # type: ignore[attr-defined]
        await pilot.pause()
        editor = f.query_one(ExposureEditor)
        assert [r["purpose"] for r in editor.rows] == ["soft", "hard"]
        await pilot.press("ctrl+s")  # times are still 0 → refused inline
        await pilot.pause()
        assert "exposure" in str(f.query_one("#e-exposures").render())
        editor.set_value([
            {"filter_grade": "00", "seconds": 9.0, "purpose": "soft", "aperture": "", "note": ""},
            {"filter_grade": "5", "seconds": 7.0, "purpose": "hard", "aperture": "", "note": ""},
        ])  # fmt: skip
        f.widget("frame").value = "14"  # type: ignore[attr-defined]
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, RollScreen)
        p = app.session.scalars(select(Print).where(Print.roll_id == roll.id)).one()
        assert p.frame == "14" and [e.filter_grade for e in p.exposures] == ["00", "5"]
        assert len(roll.prints) == 1

    run(db, scenario)


def test_new_camera_and_cancel_with_unsaved_changes(db: Any) -> None:
    async def scenario(app: FilmLogTUI, pilot: Pilot[None]) -> None:
        await pilot.press("3")
        await pilot.pause()
        pane = app.screen.query_one(CamerasPane)
        pane.new_item()
        await pilot.pause()
        f = form(app)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "required" in str(f.query_one("#e-make").render())
        f.widget("make").value = "Canon"  # type: ignore[attr-defined]
        await pilot.press("escape")  # dirty → asks first
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("n")
        await pilot.pause()
        assert app.screen is f
        f.widget("model").value = "AE-1"  # type: ignore[attr-defined]
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, MainScreen)
        assert app.session.scalar(select(Camera).where(Camera.model == "AE-1")) is not None

    run(db, scenario, demo=False)


def test_film_in_use_offers_discontinue(db: Any) -> None:
    async def scenario(app: FilmLogTUI, pilot: Pilot[None]) -> None:
        await pilot.press("4")
        await pilot.pause()
        pane = app.screen.query_one(FilmsPane)
        hp5 = next(f for f in pane.items if f.name == "HP5 Plus")
        pane.delete_item(hp5)
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()
        assert app.session.get(FilmStock, hp5.id) is not None
        assert hp5.discontinued

    run(db, scenario)


def test_search_filters_rows(db: Any) -> None:
    async def scenario(app: FilmLogTUI, pilot: Pilot[None]) -> None:
        pane = app.screen.query_one(RollsPane)
        await pilot.press("ctrl+f")
        search = pane.query_one(".search", Input)
        assert app.focused is search
        await pilot.press(*"tri-x")
        await pilot.pause()
        assert pane.table.row_count == 2

    run(db, scenario)
