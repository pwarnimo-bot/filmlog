from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage
from sqlalchemy import select
from sqlalchemy.orm import Session

from filmlog import paths
from filmlog.db.enums import ContrastMethod, ExposurePurpose
from filmlog.db.models import Camera, Print, PrintExposure
from filmlog.services.images import (
    delete_image_files,
    delete_unreferenced,
    images_of_roll,
    import_image,
    orphan_files,
)
from filmlog.services.prints import PrintFilter, list_prints, new_print_for
from filmlog.ui.images import load_thumbnail
from filmlog.ui.main_window import MainWindow
from filmlog.ui.print_form import ExposureRow
from filmlog.ui.prints_view import PrintsView
from filmlog.ui.rolls_view import RollsView
from tests.factories import chem, make_roll


def _png(path: Path, w: int = 640, h: int = 480) -> Path:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 180, 160))
    assert img.save(str(path))
    return path


def test_import_and_delete_images(tmp_path: Path) -> None:
    src = _png(tmp_path / "My Scan #1.png")
    name = import_image(src)
    assert name.startswith("My_Scan__1-") and name.endswith(".png")
    assert (paths.images_dir() / name).is_file()
    assert src.is_file()  # original untouched
    with pytest.raises(ValueError):
        import_image(
            tmp_path.joinpath("notes.txt").resolve()
            if (tmp_path / "notes.txt").write_text("x")
            else src
        )
    assert delete_image_files(["../../etc/passwd", ".thumbs", None]) == 0
    assert delete_image_files([name]) == 1
    assert not (paths.images_dir() / name).exists()


def test_thumbnail_is_generated_and_cached(qapp: object, tmp_path: Path) -> None:
    name = import_image(_png(tmp_path / "big.png", 1200, 800))
    pm = load_thumbnail(name, 160)
    assert pm is not None and pm.width() == 160 and pm.height() <= 107
    assert list(paths.thumbnails_dir().glob("big-*_160.png"))
    delete_image_files([name])
    assert not list(paths.thumbnails_dir().glob("big-*"))


def test_delete_unreferenced_keeps_used_files(session: Session, tmp_path: Path) -> None:
    used = import_image(_png(tmp_path / "a.png"))
    unused = import_image(_png(tmp_path / "b.png"))
    session.add(Camera(make="Leica", model="M6", photo=used))
    session.commit()
    assert [p.name for p in orphan_files(session)] == [unused]
    assert delete_unreferenced(session, [used, unused]) == 1
    assert (paths.images_dir() / used).exists()


def test_images_of_roll(session: Session) -> None:
    roll = make_roll(session, "2026-001")
    roll.contact_sheet_image = "c.png"
    roll.prints.append(Print(frame="1", image="p.png"))
    roll.prints.append(Print(frame="2"))
    assert sorted(images_of_roll(roll)) == ["c.png", "p.png"]


def test_new_print_copies_session_settings(session: Session) -> None:
    roll = make_roll(session, "2026-001")
    other = make_roll(session, "2026-002")
    mg = chem(session, "Ilford", "Multigrade")
    old = Print(
        roll=other,
        frame="3",
        paper_size="18×24 cm",
        developer=mg,
        dev_dilution="1+9",
        dev_time_s=60,
        contrast_method=ContrastMethod.SPLIT_GRADE,
        rating=4,
    )
    session.add(old)
    session.flush()
    p, src = new_print_for(session, roll)
    assert src is old
    assert p.roll_id == roll.id and not p.frame
    assert p.developer_id == mg.id and p.dev_time_s == 60 and p.paper_size == "18×24 cm"
    assert p.rating is None
    assert [e.purpose for e in p.exposures] == [ExposurePurpose.SOFT, ExposurePurpose.HARD]


def test_list_prints_filters(session: Session) -> None:
    roll = make_roll(session, "2026-001")
    roll.prints.append(
        Print(frame="1", is_final=True, rating=5, contrast_method=ContrastMethod.SPLIT_GRADE)
    )
    roll.prints.append(Print(frame="2", rating=2))
    session.flush()
    assert len(list_prints(session)) == 2
    assert [p.frame for p in list_prints(session, PrintFilter(final_only=True))] == ["1"]
    assert [p.frame for p in list_prints(session, PrintFilter(min_rating=3))] == ["1"]
    split = PrintFilter(contrast_method=ContrastMethod.SPLIT_GRADE)
    assert [p.frame for p in list_prints(session, split)] == ["1"]


def test_print_form_split_grade_and_total(main_window: MainWindow) -> None:
    s = main_window.ctx.session
    roll = make_roll(s, "2026-001")
    s.commit()
    main_window.show_view(1)
    view = main_window.current_view()
    assert isinstance(view, PrintsView)
    view.new_item()
    form = view.panel.print_form
    form.roll.set_current_id(roll.id)
    form.frame.setText("14")
    assert not form.save()  # no exposure time yet
    assert form.f_exp.hint.text()
    form.method.set_value(ContrastMethod.SPLIT_GRADE)
    rows = form.exposures.rows()
    assert [(r.purpose, r.filter_grade) for r in rows] == [
        (ExposurePurpose.SOFT, "00"),
        (ExposurePurpose.HARD, "5"),
    ]
    form.exposures.set_rows(
        [
            ExposureRow(ExposurePurpose.SOFT, "00", 9),
            ExposureRow(ExposurePurpose.HARD, "5", 7),
            ExposureRow(ExposurePurpose.BURN, "5", 4, note="sky"),
        ]
    )
    assert "20 s" in form.exposures.total.text()
    assert form.save()
    p = s.scalar(select(Print))
    assert p is not None and p.roll is roll and p.frame == "14"
    assert [(e.position, e.seconds) for e in p.exposures] == [(0, 9), (1, 7), (2, 4)]
    assert view.panel.table.source.rowCount() == 1


def test_duplicate_print_flow_in_roll_tab(main_window: MainWindow) -> None:
    s = main_window.ctx.session
    roll = make_roll(s, "2026-001")
    src = Print(frame="14", contrast_method=ContrastMethod.SINGLE_FILTER, rating=3)
    src.exposures = [PrintExposure(filter_grade="2½", seconds=14, purpose=ExposurePurpose.BASE)]
    roll.prints.append(src)
    s.commit()
    main_window.show_view(0)
    view = main_window.current_view()
    assert isinstance(view, RollsView)
    view.select_roll(roll.id)
    tab = view.panel.prints_tab
    assert tab.grid.thumbs.rowCount() == 1
    tab.grid.setCurrentIndex(tab.grid.thumbs.index(0))
    # Exercise the dialog's form directly (exec() would block).
    from filmlog.services.prints import duplicate_print
    from filmlog.ui.print_form import PrintDialog

    dlg = PrintDialog(main_window.ctx)
    dlg.form.fixed_roll = roll
    dlg.form.load_print(duplicate_print(src), "dup")
    assert dlg.form.is_new() and dlg.form.frame.text() == "14"
    assert dlg.form.rating.value() is None
    assert dlg.form.save()
    tab.reload()
    assert tab.grid.thumbs.rowCount() == 2
    assert len(roll.prints) == 2
    dlg.deleteLater()
