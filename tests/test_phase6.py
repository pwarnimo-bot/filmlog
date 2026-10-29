from __future__ import annotations

import json
import zipfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from filmlog.db.database import open_database
from filmlog.db.enums import ContrastMethod, RollStatus
from filmlog.db.models import Camera, Development, Print, Roll
from filmlog.services import demo
from filmlog.services.card import roll_card_html
from filmlog.services.exchange import (
    ExchangeError,
    export_csv_zip,
    export_dict,
    import_dict,
)
from filmlog.services.stats import compute
from filmlog.ui.file_actions import render_card_pdf
from filmlog.ui.main_window import MainWindow
from filmlog.ui.statistics_view import StatisticsView
from tests.factories import make_dev, make_roll


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_demo_load_matches_spec_and_removes_cleanly(session: Session) -> None:
    res = demo.load_demo(session)
    assert len(res.rolls_created) == 9 and res.cameras_created == 7
    rolls = {r.code: r for r in session.scalars(select(Roll))}
    r1 = rolls["2026-001"]
    assert r1.is_demo and r1.camera is not None and r1.camera.model == "FM2"
    assert r1.development is not None and r1.development.dev_time_s == 510
    assert r1.development.stop_chemical is not None
    assert r1.development.stop_chemical.name == "Ilfostop"
    assert len(r1.prints) == 2
    split = [p for p in r1.prints if p.contrast_method == ContrastMethod.SPLIT_GRADE][0]
    assert split.is_final and split.rating == 5
    assert [e.seconds for e in split.exposures] == [9, 7, 4]
    assert split.paper is not None and split.paper.name == "Multigrade RC Deluxe"
    d6 = rolls["2026-006"].development
    assert d6 is not None and d6.dev_time_s == 585 and d6.stop_chemical is not None
    assert d6.stop_chemical.name == "Water" and d6.rinse_time_s == 30
    assert rolls["2026-007"].push_pull_stops == 2.0
    assert rolls["2026-008"].status == RollStatus.EXPOSED and rolls["2026-008"].development is None
    assert rolls["2026-009"].status == RollStatus.LOADED
    # Loading twice adds nothing.
    again = demo.load_demo(session)
    assert again.rolls_created == [] and len(again.rolls_skipped) == 9

    # A user roll shot with a demo camera keeps that camera on removal.
    fm2 = r1.camera
    mine = make_roll(session, "2026-100")
    mine.camera = fm2
    session.commit()
    out = demo.remove_demo(session)
    assert out.rolls == 9 and out.cameras == 6 and out.cameras_kept == 1
    assert [r.code for r in session.scalars(select(Roll))] == ["2026-100"]
    assert _count(session, Print) == 0 and _count(session, Development) == 0
    assert not fm2.is_demo
    assert not demo.has_demo_data(session)


def test_json_roundtrip_into_fresh_db(session: Session, tmp_path: Path) -> None:
    demo.load_demo(session)
    data = export_dict(session)
    text = json.dumps(data)  # serialisable
    other = open_database(tmp_path / "other.db", tmp_path / "bk")
    with other.session() as s2:
        res = import_dict(s2, json.loads(text))
        s2.commit()
        assert len(res.rolls_created) == 9 and not res.warnings
        assert _count(s2, Roll) == 9 and _count(s2, Print) == 4 and _count(s2, Camera) == 7
        r = s2.scalar(select(Roll).where(Roll.code == "2026-004"))
        assert r is not None and r.development is not None
        assert r.development.dilution == "1+1" and r.prints[0].toning.startswith("Selenium")
        assert not r.is_demo  # imported data is real data
        assert r.tags[0].name == "family"
    other.engine.dispose()


def test_import_conflicts_skip_or_replace(session: Session) -> None:
    make_roll(session, "2026-001", developed=make_dev(session, 999))
    session.commit()
    data = export_dict(session)
    data["rolls"][0]["title"] = "Imported"
    asked: list[str] = []
    res = import_dict(session, data, lambda code: asked.append(code) or "skip")
    assert asked == ["2026-001"] and res.rolls_skipped == ["2026-001"]
    res = import_dict(session, data, lambda code: "replace")
    session.commit()
    assert res.rolls_replaced == ["2026-001"]
    roll = session.scalar(select(Roll))
    assert roll is not None and roll.title == "Imported"
    assert roll.development is not None and roll.development.dev_time_s == 999
    assert _count(session, Roll) == 1


def test_import_rejects_foreign_json(session: Session) -> None:
    import pytest

    with pytest.raises(ExchangeError):
        import_dict(session, {"hello": 1})


def test_csv_zip(session: Session, tmp_path: Path) -> None:
    demo.load_demo(session)
    out = tmp_path / "x.zip"
    names = export_csv_zip(session, out)
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == set(names)
        rolls = z.read("rolls.csv").decode().splitlines()
        assert rolls[0].startswith("id,") and "code" in rolls[0]
        assert len(rolls) == 10
        assert "2026-001" in z.read("rolls.csv").decode()


def test_stats(session: Session) -> None:
    demo.load_demo(session)
    st = compute(session)
    assert st.total_rolls == 9 and st.total_prints == 4 and st.final_prints == 2
    assert st.rolls_per_year == [("2026", 9)]
    assert st.top_films[0] == ("Ilford HP5 Plus 400", 3)
    assert dict(st.push_pull) == {0.0: 8, 2.0: 1}
    assert st.top_cameras[0][1] == 2


def test_card_html_and_pdf(main_window: MainWindow, tmp_path: Path) -> None:
    s = main_window.ctx.session
    demo.load_demo(s)
    roll = s.scalar(select(Roll).where(Roll.code == "2026-001"))
    assert roll is not None
    html = roll_card_html(roll)
    assert "2026-001" in html and "Split: 00 9 s + 5 7 s" in html and "8:30" in html
    assert "burn sky" in html
    pdf = tmp_path / "card.pdf"
    render_card_pdf(roll, main_window.ctx, pdf)
    assert pdf.read_bytes().startswith(b"%PDF")


def test_statistics_view(main_window: MainWindow) -> None:
    demo.load_demo(main_window.ctx.session)
    main_window.show_view(4)
    view = main_window.current_view()
    assert isinstance(view, StatisticsView)
    assert "9 rolls" in view.summary.text()
    assert view.grid.count() == 5
