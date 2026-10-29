from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path

from sqlalchemy.orm import Session

import filmlog.services as services_pkg
from filmlog.db.enums import ContrastMethod, ExposurePurpose, RollStatus
from filmlog.db.models import Camera, Print, PrintExposure, Roll
from filmlog.services import catalogue
from filmlog.services.development import find_prefill, new_development_for, past_results
from filmlog.services.prints import contrast_summary, duplicate_print, total_exposure
from filmlog.services.rolls import (
    RollFilter,
    code_exists,
    get_or_create_tags,
    list_rolls,
    parse_tags,
    suggest_code,
)
from tests.factories import chem, film, make_dev, make_roll


def test_services_have_no_qt_imports() -> None:
    root = Path(services_pkg.__file__).parent
    for py in root.glob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert not n.startswith(("PySide6", "PyQt", "filmlog.ui")), f"{py.name}: {n}"


def test_suggest_code(session: Session) -> None:
    assert suggest_code(session, 2026) == "2026-001"
    make_roll(session, "2026-001")
    make_roll(session, "2026-007")
    make_roll(session, "2026-x")  # free-form codes are ignored
    make_roll(session, "2025-040")
    assert suggest_code(session, 2026) == "2026-008"
    assert suggest_code(session, 2025) == "2025-041"
    assert code_exists(session, "2026-007")
    assert code_exists(session, "2026-X")
    assert not code_exists(session, "2026-002")


def test_list_rolls_filters_and_search(session: Session) -> None:
    cam = Camera(make="Nikon", model="FM2", nickname="the black FM2")
    session.add(cam)
    r1 = make_roll(session, "2026-001", "FP4 Plus")
    r1.camera = cam
    r1.title = "Moselle walk"
    r1.tags = get_or_create_tags(session, parse_tags("street, Family"))
    r2 = make_roll(session, "2026-002", "HP5 Plus", 1600, developed=make_dev(session, 600))
    session.flush()
    assert [r.code for r in list_rolls(session)] == ["2026-002", "2026-001"]
    assert [r.code for r in list_rolls(session, RollFilter(text="moselle"))] == ["2026-001"]
    assert [r.code for r in list_rolls(session, RollFilter(text="black fm2"))] == ["2026-001"]
    assert [r.code for r in list_rolls(session, RollFilter(text="hp5"))] == ["2026-002"]
    assert [r.code for r in list_rolls(session, RollFilter(status=RollStatus.DEVELOPED))] == [
        "2026-002"
    ]
    dev_id = chem(session, "Ilford", "ID-11").id
    assert [r.code for r in list_rolls(session, RollFilter(developer_id=dev_id))] == ["2026-002"]
    tag = r1.tags[0]
    assert [r.code for r in list_rolls(session, RollFilter(tag_id=tag.id))] == ["2026-001"]
    assert len(list_rolls(session, RollFilter(year=2026))) == 2
    assert r2.push_pull_stops == 0.0  # not computed by the model itself


def test_tags_are_case_insensitive(session: Session) -> None:
    a = get_or_create_tags(session, ["Street", "street ", ""])
    session.flush()
    b = get_or_create_tags(session, ["STREET"])
    assert len(a) == 1 and a[0] is b[0]


def test_prefill_prefers_same_film_and_ei(session: Session) -> None:
    make_roll(
        session,
        "2026-001",
        "FP4 Plus",
        125,
        developed=make_dev(session, 510, "stock", dt.date(2026, 1, 1)),
    )
    make_roll(
        session,
        "2026-002",
        "FP4 Plus",
        125,
        developed=make_dev(session, 660, "1+1", dt.date(2026, 2, 1)),
    )
    make_roll(
        session,
        "2026-003",
        "FP4 Plus",
        250,
        developed=make_dev(session, 700, "1+1", dt.date(2026, 3, 1)),
    )
    make_roll(
        session,
        "2026-004",
        "HP5 Plus",
        400,
        developed=make_dev(session, 450, "stock", dt.date(2026, 4, 1)),
    )

    same = make_roll(session, "2026-010", "FP4 Plus", 125)
    pre = find_prefill(session, same)
    assert pre is not None and pre.reason == "same_film_ei"
    assert pre.source.roll.code == "2026-002" and pre.values["dev_time_s"] == 660

    other_ei = make_roll(session, "2026-011", "FP4 Plus", 50)
    pre = find_prefill(session, other_ei)
    assert pre is not None and pre.reason == "same_film" and pre.source.roll.code == "2026-003"

    new_film = make_roll(session, "2026-012", "Pan F Plus")
    pre = find_prefill(session, new_film)
    assert pre is not None and pre.reason == "last" and pre.source.roll.code == "2026-004"

    dev, pre = new_development_for(session, same)
    assert dev.dev_time_s == 660 and dev.dilution == "1+1"
    assert dev.date_developed == dt.date.today()
    assert dev.result_rating is None


def test_prefill_none_on_empty(session: Session) -> None:
    roll = make_roll(session, "2026-001")
    dev, pre = new_development_for(session, roll)
    assert pre is None
    assert dev.temperature_c == 20.0


def test_past_results(session: Session) -> None:
    make_roll(session, "2026-001", developed=make_dev(session, 510, "stock"))
    make_roll(session, "2026-002", developed=make_dev(session, 660, "1+1"))
    make_roll(session, "2026-003", "HP5 Plus", developed=make_dev(session, 450, "stock"))
    fp4 = film(session, "FP4 Plus")
    id11 = chem(session, "Ilford", "ID-11")
    res = past_results(session, fp4.id, id11.id, "stock")
    assert [d.roll.code for d in res] == ["2026-001"]
    assert len(past_results(session, fp4.id, id11.id, None)) == 2
    assert past_results(session, None, id11.id, "stock") == []


def _exp(grade: str, s: float, purpose: ExposurePurpose, note: str = "") -> PrintExposure:
    return PrintExposure(filter_grade=grade, seconds=s, purpose=purpose, note=note)


def test_contrast_summary_and_total() -> None:
    split = [
        _exp("00", 8, ExposurePurpose.SOFT),
        _exp("5", 6, ExposurePurpose.HARD),
    ]
    assert contrast_summary(ContrastMethod.SPLIT_GRADE, split) == "Split: 00 8 s + 5 6 s"
    assert total_exposure(split) == 14
    single = [_exp("2½", 14, ExposurePurpose.BASE)]
    assert contrast_summary(ContrastMethod.SINGLE_FILTER, single) == "Grade 2½ 14 s"
    burned = split + [
        _exp("5", 4, ExposurePurpose.BURN, "sky"),
        _exp("none", 3, ExposurePurpose.DODGE),
    ]
    assert contrast_summary(ContrastMethod.SPLIT_GRADE, burned).endswith("(+1 burn, 1 dodge)")
    assert total_exposure(burned) == 18  # dodge happens within the base exposure


def test_duplicate_print_copies_settings(session: Session) -> None:
    roll = make_roll(session, "2026-001")
    p = Print(
        roll=roll,
        frame="14",
        contrast_method=ContrastMethod.SPLIT_GRADE,
        rating=5,
        is_final=True,
        image="x.jpg",
        dev_time_s=60,
    )
    p.exposures = [_exp("00", 9, ExposurePurpose.SOFT), _exp("5", 7, ExposurePurpose.HARD)]
    session.add(p)
    session.flush()
    d = duplicate_print(p)
    assert d.frame == "14" and d.roll_id == roll.id and d.dev_time_s == 60
    assert d.rating is None and not d.is_final and d.image is None
    assert [(e.filter_grade, e.seconds) for e in d.exposures] == [("00", 9), ("5", 7)]
    assert d.exposures[0] is not p.exposures[0]


def test_catalogue_usage(session: Session) -> None:
    fp4 = film(session, "FP4 Plus")
    id11 = chem(session, "Ilford", "ID-11")
    assert catalogue.can_delete(session, fp4)
    make_roll(session, "2026-001", developed=make_dev(session, 510))
    assert catalogue.usage_count(session, fp4) == 1
    assert not catalogue.can_delete(session, fp4)
    assert catalogue.usage_count(session, id11) == 1
    assert catalogue.usage_count(session, fp4.manufacturer) > 0
    water = [c for c in catalogue.chemicals(session) if c.is_builtin][0]
    assert not catalogue.can_delete(session, water)


def test_chemicals_filtered_by_kind(session: Session) -> None:
    from filmlog.db.enums import ChemicalKind

    stops = catalogue.chemicals(session, [ChemicalKind.STOP_BATH])
    assert stops[0].name == "Water"
    assert {c.kind for c in stops} == {ChemicalKind.STOP_BATH}
    devs = catalogue.chemicals(session, [ChemicalKind.FILM_DEVELOPER])
    assert all(c.kind == ChemicalKind.FILM_DEVELOPER for c in devs)
    assert len(devs) == 14


def test_roll_delete_cascades(session: Session) -> None:
    roll = make_roll(session, "2026-001", developed=make_dev(session, 510))
    roll.prints.append(Print(frame="1"))
    session.commit()
    session.delete(roll)
    session.commit()
    assert session.query(Roll).count() == 0
    assert session.query(Print).count() == 0
