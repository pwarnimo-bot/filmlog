"""Catalogue (reference data) queries and in-use checks."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from filmlog.db.enums import ChemicalKind
from filmlog.db.models import (
    AgitationPreset,
    Chemical,
    Development,
    FilmStock,
    Manufacturer,
    Paper,
    Print,
    Roll,
)

CatalogueItem = Manufacturer | FilmStock | Chemical | Paper | AgitationPreset


def manufacturers(session: Session) -> Sequence[Manufacturer]:
    return session.scalars(select(Manufacturer).order_by(func.lower(Manufacturer.name))).all()


def film_stocks(session: Session, *, include_discontinued: bool = True) -> Sequence[FilmStock]:
    q = (
        select(FilmStock)
        .join(Manufacturer)
        .options(joinedload(FilmStock.manufacturer))
        .order_by(func.lower(Manufacturer.name), func.lower(FilmStock.name))
    )
    if not include_discontinued:
        q = q.where(FilmStock.discontinued.is_(False))
    return session.scalars(q).all()


def chemicals(
    session: Session,
    kinds: Sequence[ChemicalKind] | None = None,
    *,
    include_discontinued: bool = True,
) -> Sequence[Chemical]:
    """Chemicals, optionally filtered by kind. Built-ins (Water) sort first."""
    q = (
        select(Chemical)
        .outerjoin(Manufacturer)
        .options(joinedload(Chemical.manufacturer))
        .order_by(
            Chemical.is_builtin.desc(),
            func.lower(func.coalesce(Manufacturer.name, "")),
            func.lower(Chemical.name),
        )
    )
    if kinds:
        q = q.where(Chemical.kind.in_(list(kinds)))
    if not include_discontinued:
        q = q.where(Chemical.discontinued.is_(False))
    return session.scalars(q).all()


def papers(session: Session, *, include_discontinued: bool = True) -> Sequence[Paper]:
    q = (
        select(Paper)
        .join(Manufacturer)
        .options(joinedload(Paper.manufacturer))
        .order_by(func.lower(Manufacturer.name), func.lower(Paper.name), Paper.surface)
    )
    if not include_discontinued:
        q = q.where(Paper.discontinued.is_(False))
    return session.scalars(q).all()


def agitation_presets(session: Session) -> Sequence[AgitationPreset]:
    return session.scalars(
        select(AgitationPreset).order_by(AgitationPreset.sort_order, AgitationPreset.name)
    ).all()


def _count(session: Session, q: object) -> int:
    return int(session.scalar(q) or 0)  # type: ignore[call-overload]


def usage_count(session: Session, item: CatalogueItem) -> int:
    """How many records reference ``item`` (0 → may be deleted)."""
    if isinstance(item, Manufacturer):
        return sum(
            _count(session, select(func.count()).select_from(m).where(m.manufacturer_id == item.id))
            for m in (FilmStock, Chemical, Paper)
        )
    if isinstance(item, FilmStock):
        return _count(
            session, select(func.count()).select_from(Roll).where(Roll.film_stock_id == item.id)
        )
    if isinstance(item, Paper):
        return _count(
            session, select(func.count()).select_from(Print).where(Print.paper_id == item.id)
        )
    if isinstance(item, Chemical):
        d = Development
        p = Print
        n = _count(
            session,
            select(func.count())
            .select_from(d)
            .where(
                or_(
                    d.developer_id == item.id,
                    d.stop_chemical_id == item.id,
                    d.fixer_id == item.id,
                    d.wetting_agent_id == item.id,
                )
            ),
        )
        n += _count(
            session,
            select(func.count())
            .select_from(p)
            .where(
                or_(
                    p.developer_id == item.id,
                    p.stop_chemical_id == item.id,
                    p.fixer_id == item.id,
                )
            ),
        )
        return n
    return 0  # agitation presets are copied as text, never referenced


def can_delete(session: Session, item: CatalogueItem) -> bool:
    if isinstance(item, Chemical) and item.is_builtin:
        return False
    return usage_count(session, item) == 0
