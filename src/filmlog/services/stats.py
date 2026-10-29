"""Simple statistics for the Statistics view."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from filmlog.db.models import Development, FilmStock, Print, Roll
from filmlog.services.rolls import roll_year


@dataclass
class Stats:
    total_rolls: int
    total_prints: int
    final_prints: int
    rolls_per_year: list[tuple[str, int]]
    top_films: list[tuple[str, int]]
    top_developers: list[tuple[str, int]]
    top_cameras: list[tuple[str, int]]
    push_pull: list[tuple[float, int]]  # (stops, rolls)


def compute(session: Session, top: int = 8) -> Stats:
    rolls = (
        session.scalars(
            select(Roll).options(
                joinedload(Roll.film_stock).joinedload(FilmStock.manufacturer),
                joinedload(Roll.camera),
                joinedload(Roll.development).joinedload(Development.developer),
            )
        )
        .unique()
        .all()
    )
    years: Counter[str] = Counter()
    films: Counter[str] = Counter()
    devs: Counter[str] = Counter()
    cams: Counter[str] = Counter()
    pp: Counter[float] = Counter()
    for r in rolls:
        y = roll_year(r)
        years[str(y) if y else "?"] += 1
        films[r.film_stock.display_name] += 1
        if r.camera is not None:
            cams[r.camera.display_name] += 1
        if r.development is not None and r.development.developer is not None:
            dil = f" {r.development.dilution}" if r.development.dilution else ""
            devs[r.development.developer.display_name + dil] += 1
        pp[round(round(r.push_pull_stops * 3) / 3, 2)] += 1
    prints = session.scalars(select(Print.is_final)).all()
    return Stats(
        total_rolls=len(rolls),
        total_prints=len(prints),
        final_prints=sum(1 for f in prints if f),
        rolls_per_year=sorted(years.items()),
        top_films=films.most_common(top),
        top_developers=devs.most_common(top),
        top_cameras=cams.most_common(top),
        push_pull=sorted(pp.items()),
    )
