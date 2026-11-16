# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dropdown options built from the catalogue and enums."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from filmlog.db.enums import CameraStatus, ChemicalKind
from filmlog.services import cameras as camera_service
from filmlog.services import catalogue
from filmlog.tui.forms import NEW

_SPECIAL = {
    "bw_negative": "B&W negative",
    "bw_reversal": "B&W reversal",
    "bw_chromogenic": "B&W chromogenic (C-41)",
    "mf_slr": "Medium-format SLR",
    "viewfinder": "Viewfinder / compact",
    "large_format": "Large format",
    "rc": "RC",
    "fb": "FB",
    "slr": "SLR",
    "tlr": "TLR",
    "washing_aid": "Hypo clear / washing aid",
    "variable": "Variable contrast",
    "semi_matt": "Semi-matt",
}


def label(value: StrEnum | str | None) -> str:
    if value is None:
        return ""
    v = value.value if isinstance(value, StrEnum) else value
    if v in _SPECIAL:
        return _SPECIAL[v]
    if v and v[0].isdigit():
        return v.replace("x", "×")
    return v.replace("_", " ").capitalize()


def enum_options(cls: type[StrEnum]) -> list[tuple[str, Any]]:
    return [(label(v), v) for v in cls]


def film_options(session: Session, current_id: int | None = None) -> list[tuple[str, Any]]:
    opts: list[tuple[str, Any]] = [
        (f.display_name + (" (discontinued)" if f.discontinued else ""), f.id)
        for f in catalogue.film_stocks(session)
        if not f.discontinued or f.id == current_id
    ]
    return opts + [("+ New film stock…", NEW)]


def chem_options(
    session: Session, kinds: Sequence[ChemicalKind], current_id: int | None = None
) -> list[tuple[str, Any]]:
    return [
        (c.display_name + (f"  ({c.common_dilutions})" if c.common_dilutions else ""), c.id)
        for c in catalogue.chemicals(session, kinds)
        if not c.discontinued or c.id == current_id
    ]


def paper_options(session: Session, current_id: int | None = None) -> list[tuple[str, Any]]:
    return [
        (p.display_name + f" — {p.base.value.upper()}", p.id)
        for p in catalogue.papers(session)
        if not p.discontinued or p.id == current_id
    ]


def camera_options(session: Session) -> list[tuple[str, Any]]:
    out = []
    for c in camera_service.list_cameras(session):
        suffix = "" if c.status == CameraStatus.ACTIVE else f" ({c.status.value})"
        out.append((c.display_name + suffix, c.id))
    return out


def manufacturer_options(session: Session) -> list[tuple[str, Any]]:
    return [(m.name, m.id) for m in catalogue.manufacturers(session)]


def dilution_suggestions(session: Session, chem_id: int | None) -> list[str]:
    from filmlog.db.enums import DEFAULT_DILUTIONS
    from filmlog.db.models import Chemical

    chem = session.get(Chemical, chem_id) if chem_id else None
    own = chem.dilution_list if chem else []
    return own + [d for d in DEFAULT_DILUTIONS if d not in own]
