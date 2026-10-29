"""Development records: pre-fill lookup and past results ("recipes")."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from filmlog.db.enums import RollStatus
from filmlog.db.models import Development, Roll

# Fields copied when pre-filling a new development from a previous one.
PREFILL_FIELDS: tuple[str, ...] = (
    "developer_id",
    "dilution",
    "temperature_c",
    "dev_time_s",
    "agitation",
    "presoak_s",
    "stop_chemical_id",
    "stop_time_s",
    "rinse_time_s",
    "fixer_id",
    "fixer_dilution",
    "fix_time_s",
    "wash_time_s",
    "wash_method",
    "wetting_agent_id",
    "wetting_time_s",
    "tank",
)


@dataclass
class Prefill:
    source: Development
    reason: str  # "same_film_ei" | "same_film" | "last"
    values: dict[str, Any]


def _recent() -> Select[Development]:
    return (
        select(Development)
        .join(Roll, Development.roll_id == Roll.id)
        .options(joinedload(Development.roll))
        .order_by(
            Development.date_developed.desc().nulls_last(),
            Development.id.desc(),
        )
    )


def find_prefill(session: Session, roll: Roll) -> Prefill | None:
    """Most recent development with same film + EI, else same film, else the last one."""
    base = _recent()
    if roll.id is not None:
        base = base.where(Development.roll_id != roll.id)
    attempts: list[tuple[str, Select[Development]]] = [
        (
            "same_film_ei",
            base.where(Roll.film_stock_id == roll.film_stock_id, Roll.shot_iso == roll.shot_iso),
        ),
        ("same_film", base.where(Roll.film_stock_id == roll.film_stock_id)),
        ("last", base),
    ]
    for reason, q in attempts:
        dev = session.scalars(q.limit(1)).first()
        if dev is not None:
            return Prefill(dev, reason, prefill_values(dev))
    return None


def prefill_values(dev: Development) -> dict[str, Any]:
    return {f: getattr(dev, f) for f in PREFILL_FIELDS}


def new_development_for(session: Session, roll: Roll) -> tuple[Development, Prefill | None]:
    """A new (unsaved) Development for ``roll``, pre-filled when possible."""
    dev = Development(date_developed=dt.date.today(), temperature_c=20.0)
    pre = find_prefill(session, roll)
    if pre is not None:
        for k, v in pre.values.items():
            setattr(dev, k, v)
    return dev, pre


def past_results(
    session: Session,
    film_stock_id: int | None,
    developer_id: int | None,
    dilution: str | None,
    *,
    exclude_roll_id: int | None = None,
    limit: int = 50,
) -> Sequence[Development]:
    """Previous developments with the same film stock + developer (+ dilution if given)."""
    if film_stock_id is None:
        return []
    q = _recent().where(Roll.film_stock_id == film_stock_id)
    if developer_id is not None:
        q = q.where(Development.developer_id == developer_id)
    if dilution:
        q = q.where(Development.dilution == dilution.strip())
    if exclude_roll_id is not None:
        q = q.where(Development.roll_id != exclude_roll_id)
    return session.scalars(q.limit(limit)).unique().all()


def mark_developed(roll: Roll, dev: Development) -> None:
    roll.status = RollStatus.DEVELOPED
    roll.development = dev
