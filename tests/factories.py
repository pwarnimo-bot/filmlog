"""Helpers for building test records."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from filmlog.db.enums import ChemicalKind, RollStatus
from filmlog.db.models import Chemical, Development, FilmStock, Manufacturer, Roll


def film(session: Session, name: str) -> FilmStock:
    f = session.scalar(select(FilmStock).where(FilmStock.name == name))
    assert f is not None, name
    return f


def chem(session: Session, mfr: str, name: str) -> Chemical:
    c = session.scalar(
        select(Chemical).join(Manufacturer).where(Manufacturer.name == mfr, Chemical.name == name)
    )
    assert c is not None, name
    return c


def water(session: Session) -> Chemical:
    c = session.scalar(
        select(Chemical).where(Chemical.name == "Water", Chemical.kind == ChemicalKind.STOP_BATH)
    )
    assert c is not None
    return c


def make_roll(
    session: Session,
    code: str,
    film_name: str = "FP4 Plus",
    ei: int | None = None,
    *,
    developed: Development | None = None,
) -> Roll:
    f = film(session, film_name)
    roll = Roll(code=code, film_stock=f, shot_iso=ei or f.box_iso)
    if developed is not None:
        roll.status = RollStatus.DEVELOPED
        roll.development = developed
    session.add(roll)
    session.flush()
    return roll


def make_dev(
    session: Session, dev_time_s: int, dilution: str = "stock", date: dt.date | None = None
) -> Development:
    return Development(
        developer=chem(session, "Ilford", "ID-11"),
        dilution=dilution,
        dev_time_s=dev_time_s,
        temperature_c=20.0,
        date_developed=date or dt.date(2026, 1, 1),
    )
