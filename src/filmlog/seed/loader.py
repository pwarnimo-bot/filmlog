# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Load seed data from the JSON files in this package."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from filmlog.db.enums import (
    ChemicalForm,
    ChemicalKind,
    ContrastType,
    FilmType,
    PaperBase,
    PaperSurface,
    PaperTone,
)
from filmlog.db.models import AgitationPreset, Chemical, FilmStock, Manufacturer, Paper


def read_seed(name: str) -> dict[str, Any]:
    text = (resources.files("filmlog.seed") / name).read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def catalogue_is_empty(session: Session) -> bool:
    return not session.scalar(select(func.count()).select_from(Manufacturer))


def get_or_create_manufacturer(
    session: Session, name: str | None, country: str | None = None
) -> Manufacturer | None:
    if not name:
        return None
    m = session.scalar(select(Manufacturer).where(Manufacturer.name == name))
    if m is None:
        m = Manufacturer(name=name, country=country)
        session.add(m)
        session.flush()
    return m


def load_catalogue(session: Session, data: dict[str, Any] | None = None) -> dict[str, int]:
    """Insert the catalogue seed. Existing entries (same natural key) are skipped."""
    data = read_seed("catalogue.json") if data is None else data
    counts = {"manufacturers": 0, "film_stocks": 0, "chemicals": 0, "papers": 0, "presets": 0}

    for m in data.get("manufacturers", []):
        if session.scalar(select(Manufacturer).where(Manufacturer.name == m["name"])) is None:
            session.add(Manufacturer(name=m["name"], country=m.get("country")))
            counts["manufacturers"] += 1
    session.flush()

    for f in data.get("film_stocks", []):
        mfr = get_or_create_manufacturer(session, f["manufacturer"])
        assert mfr is not None
        exists = session.scalar(
            select(FilmStock).where(
                FilmStock.manufacturer_id == mfr.id, FilmStock.name == f["name"]
            )
        )
        if exists:
            continue
        session.add(
            FilmStock(
                manufacturer=mfr,
                name=f["name"],
                box_iso=int(f["box_iso"]),
                type=FilmType(f.get("type", FilmType.BW_NEGATIVE)),
                formats_available=f.get("formats_available", ""),
                aliases=f.get("aliases", ""),
                discontinued=bool(f.get("discontinued", False)),
                notes=f.get("notes", ""),
            )
        )
        counts["film_stocks"] += 1

    for c in data.get("chemicals", []):
        mfr = get_or_create_manufacturer(session, c.get("manufacturer"))
        kind = ChemicalKind(c["kind"])
        same_mfr = Chemical.manufacturer_id == mfr.id if mfr else Chemical.manufacturer_id.is_(None)
        found_chem = session.scalar(
            select(Chemical).where(same_mfr, Chemical.name == c["name"], Chemical.kind == kind)
        )
        if found_chem:
            continue
        session.add(
            Chemical(
                manufacturer=mfr,
                name=c["name"],
                kind=kind,
                common_dilutions=c.get("common_dilutions", ""),
                form=ChemicalForm(c.get("form", ChemicalForm.LIQUID)),
                is_builtin=bool(c.get("is_builtin", False)),
                notes=c.get("notes", ""),
            )
        )
        counts["chemicals"] += 1

    for p in data.get("papers", []):
        mfr = get_or_create_manufacturer(session, p["manufacturer"])
        assert mfr is not None
        surface = PaperSurface(p.get("surface", PaperSurface.GLOSSY))
        found_paper = session.scalar(
            select(Paper).where(
                Paper.manufacturer_id == mfr.id, Paper.name == p["name"], Paper.surface == surface
            )
        )
        if found_paper:
            continue
        session.add(
            Paper(
                manufacturer=mfr,
                name=p["name"],
                base=PaperBase(p.get("base", PaperBase.RC)),
                contrast_type=ContrastType(p.get("contrast_type", ContrastType.VARIABLE)),
                grade=p.get("grade"),
                surface=surface,
                tone=PaperTone(p.get("tone", PaperTone.NEUTRAL)),
                notes=p.get("notes", ""),
            )
        )
        counts["papers"] += 1

    for a in data.get("agitation_presets", []):
        if session.scalar(select(AgitationPreset).where(AgitationPreset.name == a["name"])):
            continue
        session.add(
            AgitationPreset(
                name=a["name"], text=a.get("text", ""), sort_order=a.get("sort_order", 0)
            )
        )
        counts["presets"] += 1

    session.flush()
    return counts


def ensure_catalogue_seeded(session: Session) -> bool:
    """Seed the catalogue on first launch (empty DB). Returns True if seeded."""
    if not catalogue_is_empty(session):
        return False
    load_catalogue(session)
    session.commit()
    return True
