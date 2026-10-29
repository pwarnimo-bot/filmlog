"""Print helpers: exposure summaries, totals, duplication, queries."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from filmlog.db.enums import ContrastMethod, ExposurePurpose
from filmlog.db.models import FilmStock, Paper, Print, PrintExposure, Roll
from filmlog.services.timefmt import format_seconds

# Columns copied by "Duplicate print" (everything except identity/result fields).
COPY_FIELDS: tuple[str, ...] = (
    "roll_id",
    "frame",
    "title",
    "paper_id",
    "paper_size",
    "enlarger",
    "enlarging_lens",
    "aperture",
    "head_height_cm",
    "contrast_method",
    "developer_id",
    "dev_dilution",
    "dev_time_s",
    "dev_temperature_c",
    "stop_chemical_id",
    "stop_time_s",
    "fixer_id",
    "fixer_dilution",
    "fix_time_s",
    "wash_time_s",
    "toning",
    "notes",
)

_MAIN = (ExposurePurpose.BASE, ExposurePurpose.SOFT, ExposurePurpose.HARD)


def total_exposure(exposures: Sequence[PrintExposure]) -> float:
    """Total enlarger-on time. Dodging happens *during* the base exposure, so it adds 0."""
    return round(sum(e.seconds or 0.0 for e in exposures if e.purpose != ExposurePurpose.DODGE), 2)


def _grade(g: str) -> str:
    return "no filter" if g in ("", "none") else g


def contrast_summary(method: ContrastMethod, exposures: Sequence[PrintExposure]) -> str:
    """Short description such as "Split: 00 8 s + 5 6 s" or "Grade 2½ 14 s"."""
    main = [e for e in exposures if e.purpose in _MAIN]
    extra = [e for e in exposures if e.purpose not in _MAIN]
    if method == ContrastMethod.SPLIT_GRADE:
        body = " + ".join(f"{_grade(e.filter_grade)} {format_seconds(e.seconds)}" for e in main)
        text = f"Split: {body}" if body else "Split"
    elif method == ContrastMethod.NO_FILTER:
        text = "No filter " + " + ".join(format_seconds(e.seconds) for e in main)
    elif method == ContrastMethod.GRADED_PAPER:
        text = "Graded " + " + ".join(format_seconds(e.seconds) for e in main)
    else:
        text = " + ".join(
            f"Grade {_grade(e.filter_grade)} {format_seconds(e.seconds)}" for e in main
        )
        text = text or "Single filter"
    if extra:
        burns = sum(1 for e in extra if e.purpose == ExposurePurpose.BURN)
        dodges = sum(1 for e in extra if e.purpose == ExposurePurpose.DODGE)
        flashes = sum(1 for e in extra if e.purpose == ExposurePurpose.FLASH)
        bits = []
        if burns:
            bits.append(f"{burns} burn" + ("s" if burns > 1 else ""))
        if dodges:
            bits.append(f"{dodges} dodge" + ("s" if dodges > 1 else ""))
        if flashes:
            bits.append("flash")
        text += " (+" + ", ".join(bits) + ")"
    return text.strip()


def copy_exposures(exposures: Sequence[PrintExposure]) -> list[PrintExposure]:
    return [
        PrintExposure(
            position=i,
            filter_grade=e.filter_grade,
            seconds=e.seconds,
            aperture=e.aperture,
            purpose=e.purpose,
            note=e.note,
        )
        for i, e in enumerate(exposures)
    ]


def duplicate_print(src: Print) -> Print:
    """A new, unsaved print with all settings copied; result fields reset."""
    p = Print(**{f: getattr(src, f) for f in COPY_FIELDS})
    p.date_printed = dt.date.today()
    p.is_final = False
    p.rating = None
    p.image = None
    p.is_demo = False
    p.exposures = copy_exposures(src.exposures)
    return p


def default_exposures(method: ContrastMethod) -> list[PrintExposure]:
    if method == ContrastMethod.SPLIT_GRADE:
        return [
            PrintExposure(position=0, filter_grade="00", purpose=ExposurePurpose.SOFT, seconds=0.0),
            PrintExposure(position=1, filter_grade="5", purpose=ExposurePurpose.HARD, seconds=0.0),
        ]
    grade = "2" if method == ContrastMethod.SINGLE_FILTER else "none"
    return [
        PrintExposure(position=0, filter_grade=grade, purpose=ExposurePurpose.BASE, seconds=0.0)
    ]


@dataclass
class PrintFilter:
    text: str = ""
    paper_id: int | None = None
    developer_id: int | None = None
    contrast_method: ContrastMethod | None = None
    final_only: bool = False
    min_rating: int | None = None
    roll_id: int | None = None


def list_prints(session: Session, flt: PrintFilter | None = None) -> Sequence[Print]:
    flt = flt or PrintFilter()
    q = select(Print).options(
        joinedload(Print.roll).joinedload(Roll.film_stock).joinedload(FilmStock.manufacturer),
        joinedload(Print.paper).joinedload(Paper.manufacturer),
        joinedload(Print.developer),
        selectinload(Print.exposures),
    )
    if flt.text.strip():
        like = f"%{flt.text.strip()}%"
        q = q.join(Roll, Print.roll_id == Roll.id).where(
            or_(
                Print.title.ilike(like),
                Print.frame.ilike(like),
                Print.notes.ilike(like),
                Roll.code.ilike(like),
                Roll.title.ilike(like),
            )
        )
    if flt.paper_id is not None:
        q = q.where(Print.paper_id == flt.paper_id)
    if flt.developer_id is not None:
        q = q.where(Print.developer_id == flt.developer_id)
    if flt.contrast_method is not None:
        q = q.where(Print.contrast_method == flt.contrast_method)
    if flt.final_only:
        q = q.where(Print.is_final.is_(True))
    if flt.min_rating is not None:
        q = q.where(Print.rating >= flt.min_rating)
    if flt.roll_id is not None:
        q = q.where(Print.roll_id == flt.roll_id)
    return session.scalars(q.order_by(Print.date_printed.desc(), Print.id.desc())).unique().all()


# Settings carried over to a new print from the previous one (same darkroom session).
SESSION_FIELDS: tuple[str, ...] = (
    "paper_id",
    "paper_size",
    "enlarger",
    "enlarging_lens",
    "aperture",
    "head_height_cm",
    "contrast_method",
    "developer_id",
    "dev_dilution",
    "dev_time_s",
    "dev_temperature_c",
    "stop_chemical_id",
    "stop_time_s",
    "fixer_id",
    "fixer_dilution",
    "fix_time_s",
    "wash_time_s",
)


def last_print(session: Session, roll_id: int | None = None) -> Print | None:
    """Most recent print of ``roll_id`` if any, else the most recent print overall."""
    order = (Print.date_printed.desc().nulls_last(), Print.id.desc())
    if roll_id is not None:
        p = session.scalars(select(Print).where(Print.roll_id == roll_id).order_by(*order)).first()
        if p is not None:
            return p
    return session.scalars(select(Print).order_by(*order)).first()


def new_print_for(session: Session, roll: Roll | None) -> tuple[Print, Print | None]:
    """A new unsaved print, with paper/enlarger/chemistry taken from the last print."""
    p = Print(date_printed=dt.date.today(), contrast_method=ContrastMethod.SINGLE_FILTER)
    if roll is not None:
        p.roll_id = roll.id
    src = last_print(session, roll.id if roll is not None else None)
    if src is not None:
        for f in SESSION_FIELDS:
            setattr(p, f, getattr(src, f))
    p.exposures = default_exposures(p.contrast_method)
    return p, src
