"""Roll queries and helpers."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from filmlog.db.enums import RollStatus
from filmlog.db.models import (
    Camera,
    Development,
    FilmStock,
    Manufacturer,
    Roll,
    Tag,
)
from filmlog.services.pushpull import compute_stops


def suggest_code(session: Session, year: int | None = None) -> str:
    """Next free ``YYYY-NNN`` code for the given year (default: this year)."""
    year = year or dt.date.today().year
    prefix = f"{year}-"
    codes = session.scalars(select(Roll.code).where(Roll.code.like(f"{prefix}%"))).all()
    used = set()
    for c in codes:
        m = re.fullmatch(rf"{year}-(\d+)", c)
        if m:
            used.add(int(m.group(1)))
    n = (max(used) + 1) if used else 1
    return f"{prefix}{n:03d}"


def code_exists(session: Session, code: str, exclude_id: int | None = None) -> bool:
    q = select(Roll.id).where(func.lower(Roll.code) == code.strip().lower())
    if exclude_id is not None:
        q = q.where(Roll.id != exclude_id)
    return session.scalar(q) is not None


def default_push_pull(ei: int, film: FilmStock | None) -> float:
    return compute_stops(ei, film.box_iso) if film else 0.0


@dataclass
class RollFilter:
    text: str = ""
    status: RollStatus | None = None
    film_stock_id: int | None = None
    camera_id: int | None = None
    developer_id: int | None = None
    year: int | None = None
    tag_id: int | None = None


def _roll_query() -> Select[Roll]:
    return select(Roll).options(
        joinedload(Roll.film_stock).joinedload(FilmStock.manufacturer),
        joinedload(Roll.camera),
        joinedload(Roll.development).joinedload(Development.developer),
        selectinload(Roll.tags),
        selectinload(Roll.prints),
    )


def roll_year(roll: Roll) -> int | None:
    d = roll.date_loaded or roll.date_finished
    if roll.development and roll.development.date_developed:
        d = d or roll.development.date_developed
    if d:
        return d.year
    m = re.match(r"(\d{4})-", roll.code)
    return int(m.group(1)) if m else roll.created_at.year if roll.created_at else None


def list_rolls(session: Session, flt: RollFilter | None = None) -> Sequence[Roll]:
    flt = flt or RollFilter()
    q = _roll_query()
    if flt.text.strip():
        like = f"%{flt.text.strip()}%"
        q = (
            q.outerjoin(FilmStock, Roll.film_stock_id == FilmStock.id)
            .outerjoin(Manufacturer, FilmStock.manufacturer_id == Manufacturer.id)
            .outerjoin(Camera, Roll.camera_id == Camera.id)
            .where(
                or_(
                    Roll.code.ilike(like),
                    Roll.title.ilike(like),
                    Roll.notes.ilike(like),
                    Roll.subject_location.ilike(like),
                    FilmStock.name.ilike(like),
                    Manufacturer.name.ilike(like),
                    Camera.make.ilike(like),
                    Camera.model.ilike(like),
                    Camera.nickname.ilike(like),
                )
            )
        )
    if flt.status is not None:
        q = q.where(Roll.status == flt.status)
    if flt.film_stock_id is not None:
        q = q.where(Roll.film_stock_id == flt.film_stock_id)
    if flt.camera_id is not None:
        q = q.where(Roll.camera_id == flt.camera_id)
    if flt.developer_id is not None:
        q = q.where(
            Roll.id.in_(
                select(Development.roll_id).where(Development.developer_id == flt.developer_id)
            )
        )
    if flt.tag_id is not None:
        q = q.where(Roll.tags.any(Tag.id == flt.tag_id))
    rolls = session.scalars(q.order_by(Roll.code.desc())).unique().all()
    if flt.year is not None:
        rolls = [r for r in rolls if roll_year(r) == flt.year]
    return rolls


def roll_years(session: Session) -> list[int]:
    years = {y for r in session.scalars(_roll_query()).unique() if (y := roll_year(r))}
    return sorted(years, reverse=True)


def get_roll(session: Session, roll_id: int) -> Roll | None:
    return session.get(Roll, roll_id)


def get_or_create_tags(session: Session, names: Sequence[str]) -> list[Tag]:
    tags: list[Tag] = []
    seen: set[str] = set()
    for raw in names:
        name = raw.strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        tag = session.scalar(select(Tag).where(func.lower(Tag.name) == name.lower()))
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
        tags.append(tag)
    return tags


def parse_tags(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


def prune_unused_tags(session: Session) -> int:
    from filmlog.db.models import roll_tag

    unused = session.scalars(select(Tag).where(~Tag.id.in_(select(roll_tag.c.tag_id)))).all()
    for t in unused:
        session.delete(t)
    return len(unused)


def all_tags(session: Session) -> Sequence[Tag]:
    return session.scalars(select(Tag).order_by(Tag.name)).all()


def can_have_development(roll: Roll) -> bool:
    return roll.status == RollStatus.DEVELOPED
