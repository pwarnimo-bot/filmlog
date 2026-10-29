"""Export (CSV zip, nested JSON) and JSON import (merge by roll code).

The JSON format references catalogue entries by natural keys (manufacturer +
name …) rather than database ids, so a file can be imported into any FilmLog
database. The demo data in ``filmlog/seed/demo.json`` uses the same format.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Date, DateTime, Table, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.sqltypes import Enum as SAEnum

from filmlog import __version__
from filmlog.db.models import (
    AgitationPreset,
    Base,
    Camera,
    Chemical,
    Development,
    FilmStock,
    Manufacturer,
    Paper,
    Print,
    PrintExposure,
    Roll,
    RollImage,
    Tag,
    development_roll,
    roll_tag,
)
from filmlog.seed.loader import load_catalogue
from filmlog.services.rolls import get_or_create_tags

FORMAT = "filmlog-export"
VERSION = 1
SKIP = {"id", "created_at", "updated_at"}

ConflictChoice = Literal["skip", "replace"]


# --------------------------------------------------------------------------- helpers


def _to_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value


def _columns(obj: Base, exclude: set[str] = frozenset()) -> dict[str, Any]:  # type: ignore[assignment]
    table = obj.__table__  # type: ignore[attr-defined]
    out: dict[str, Any] = {}
    for col in table.columns:
        if col.key in SKIP or col.key in exclude or col.foreign_keys:
            continue
        out[col.key] = _to_json(getattr(obj, col.key))
    return out


def _from_json(model: type[Base], data: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON values to column types; unknown keys are ignored."""
    table = model.__table__  # type: ignore[attr-defined]
    out: dict[str, Any] = {}
    for col in table.columns:
        if col.key in SKIP or col.foreign_keys or col.key not in data:
            continue
        v = data[col.key]
        if v is not None:
            if isinstance(col.type, DateTime):
                v = dt.datetime.fromisoformat(v)
            elif isinstance(col.type, Date):
                v = dt.date.fromisoformat(v)
            elif isinstance(col.type, SAEnum) and col.type.enum_class is not None:
                v = col.type.enum_class(v)
        out[col.key] = v
    return out


def _mref(m: Manufacturer | None) -> str | None:
    return m.name if m is not None else None


def _chem_ref(c: Chemical | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {"manufacturer": _mref(c.manufacturer), "name": c.name, "kind": c.kind.value}


def _paper_ref(p: Paper | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"manufacturer": _mref(p.manufacturer), "name": p.name, "surface": p.surface.value}


def _film_ref(f: FilmStock) -> dict[str, Any]:
    return {"manufacturer": _mref(f.manufacturer), "name": f.name}


def _camera_key(c: Camera) -> str:
    return f"camera-{c.id}"


# --------------------------------------------------------------------------- JSON export


def _catalogue_dict(session: Session) -> dict[str, Any]:
    return {
        "manufacturers": [
            _columns(m) for m in session.scalars(select(Manufacturer).order_by(Manufacturer.name))
        ],
        "film_stocks": [
            {"manufacturer": _mref(f.manufacturer), **_columns(f)}
            for f in session.scalars(select(FilmStock).order_by(FilmStock.id))
        ],
        "chemicals": [
            {"manufacturer": _mref(c.manufacturer), **_columns(c)}
            for c in session.scalars(select(Chemical).order_by(Chemical.id))
        ],
        "papers": [
            {"manufacturer": _mref(p.manufacturer), **_columns(p)}
            for p in session.scalars(select(Paper).order_by(Paper.id))
        ],
        "agitation_presets": [
            _columns(a)
            for a in session.scalars(select(AgitationPreset).order_by(AgitationPreset.id))
        ],
    }


def _print_dict(p: Print) -> dict[str, Any]:
    d = _columns(p, {"is_demo"})
    d["paper"] = _paper_ref(p.paper)
    d["developer"] = _chem_ref(p.developer)
    d["stop_chemical"] = _chem_ref(p.stop_chemical)
    d["fixer"] = _chem_ref(p.fixer)
    d["exposures"] = [_columns(e) for e in p.exposures]
    return d


def _development_dict(dev: Development) -> dict[str, Any]:
    d = _columns(dev)
    d["developer"] = _chem_ref(dev.developer)
    d["stop_chemical"] = _chem_ref(dev.stop_chemical)
    d["fixer"] = _chem_ref(dev.fixer)
    d["wetting_agent"] = _chem_ref(dev.wetting_agent)
    d["developed_with"] = [r.code for r in dev.developed_with_rolls]
    return d


def _roll_dict(r: Roll) -> dict[str, Any]:
    d = _columns(r, {"is_demo"})
    d["film_stock"] = _film_ref(r.film_stock)
    d["camera"] = _camera_key(r.camera) if r.camera is not None else None
    d["tags"] = [t.name for t in r.tags]
    d["images"] = [{"filename": i.filename, "caption": i.caption} for i in r.images]
    d["development"] = _development_dict(r.development) if r.development else None
    d["prints"] = [_print_dict(p) for p in r.prints]
    return d


def export_dict(session: Session) -> dict[str, Any]:
    cameras = session.scalars(select(Camera).order_by(Camera.id)).all()
    rolls = session.scalars(select(Roll).order_by(Roll.code)).all()
    return {
        "format": FORMAT,
        "version": VERSION,
        "app_version": __version__,
        "exported_at": dt.datetime.now().replace(microsecond=0).isoformat(),
        "catalogue": _catalogue_dict(session),
        "cameras": [{"key": _camera_key(c), **_columns(c, {"is_demo"})} for c in cameras],
        "rolls": [_roll_dict(r) for r in rolls],
    }


def export_json(session: Session, path: Path) -> None:
    path.write_text(json.dumps(export_dict(session), indent=2, ensure_ascii=False), "utf-8")


# --------------------------------------------------------------------------- CSV export

CSV_MODELS: tuple[tuple[str, type[Base] | Table], ...] = (
    ("manufacturers", Manufacturer),
    ("film_stocks", FilmStock),
    ("chemicals", Chemical),
    ("papers", Paper),
    ("agitation_presets", AgitationPreset),
    ("cameras", Camera),
    ("rolls", Roll),
    ("tags", Tag),
    ("roll_tags", roll_tag),
    ("roll_images", RollImage),
    ("developments", Development),
    ("development_rolls", development_roll),
    ("prints", Print),
    ("print_exposures", PrintExposure),
)


def _csv_text(session: Session, target: type[Base] | Table) -> str:
    table: Table = target if isinstance(target, Table) else target.__table__  # type: ignore[assignment]
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = [c for c in table.columns if c.primary_key] + [
        c for c in table.columns if not c.primary_key
    ]
    w.writerow([c.key for c in cols])
    for row in session.execute(select(*cols).order_by(*table.primary_key.columns)).all():
        w.writerow(["" if v is None else _to_json(v) for v in row])
    return buf.getvalue()


def export_csv_zip(session: Session, path: Path) -> list[str]:
    """One CSV per table (ids kept so rows can be joined), zipped."""
    names: list[str] = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, target in CSV_MODELS:
            z.writestr(f"{name}.csv", _csv_text(session, target))
            names.append(f"{name}.csv")
    return names


# --------------------------------------------------------------------------- JSON import


@dataclass
class ImportResult:
    rolls_created: list[str] = field(default_factory=list)
    rolls_replaced: list[str] = field(default_factory=list)
    rolls_skipped: list[str] = field(default_factory=list)
    cameras_created: int = 0
    catalogue_created: int = 0
    warnings: list[str] = field(default_factory=list)


class ExchangeError(ValueError):
    pass


def _find_manufacturer(session: Session, name: str | None) -> Manufacturer | None:
    if not name:
        return None
    return session.scalar(select(Manufacturer).where(func.lower(Manufacturer.name) == name.lower()))


class _Resolver:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.cameras: dict[str, Camera] = {}

    def film(self, ref: dict[str, Any]) -> FilmStock | None:
        m = _find_manufacturer(self.s, ref.get("manufacturer"))
        if m is None:
            return None
        return self.s.scalar(
            select(FilmStock).where(
                FilmStock.manufacturer_id == m.id, func.lower(FilmStock.name) == ref["name"].lower()
            )
        )

    def chem(self, ref: dict[str, Any] | None) -> Chemical | None:
        if not ref:
            return None
        m = _find_manufacturer(self.s, ref.get("manufacturer"))
        q = select(Chemical).where(
            func.lower(Chemical.name) == ref["name"].lower(), Chemical.kind == ref["kind"]
        )
        q = (
            q.where(Chemical.manufacturer_id == m.id)
            if m
            else q.where(Chemical.manufacturer_id.is_(None))
        )
        return self.s.scalar(q)

    def paper(self, ref: dict[str, Any] | None) -> Paper | None:
        if not ref:
            return None
        m = _find_manufacturer(self.s, ref.get("manufacturer"))
        if m is None:
            return None
        q = select(Paper).where(
            Paper.manufacturer_id == m.id, func.lower(Paper.name) == ref["name"].lower()
        )
        if ref.get("surface"):
            q = q.where(Paper.surface == ref["surface"])
        return self.s.scalars(q).first()


def _import_cameras(
    session: Session, data: list[dict[str, Any]], res: ImportResult, demo: bool
) -> dict[str, Camera]:
    out: dict[str, Camera] = {}
    for c in data:
        fields = _from_json(Camera, c)
        existing = session.scalar(
            select(Camera).where(
                Camera.make == fields.get("make", ""),
                Camera.model == fields.get("model", ""),
                Camera.nickname == (fields.get("nickname") or ""),
                Camera.serial_number == (fields.get("serial_number") or ""),
            )
        )
        if existing is None:
            existing = Camera(**fields)
            existing.is_demo = demo
            session.add(existing)
            res.cameras_created += 1
        out[c["key"]] = existing
    session.flush()
    return out


def _apply_chems(
    obj: Any, data: dict[str, Any], r: _Resolver, names: tuple[str, ...], res: ImportResult
) -> None:
    for name in names:
        ref = data.get(name)
        chem = r.chem(ref)
        if ref and chem is None:
            res.warnings.append(f"Unknown chemical {ref.get('name')!r}")
        setattr(obj, name, chem)


def import_dict(
    session: Session,
    data: dict[str, Any],
    on_conflict: Callable[[str], ConflictChoice] = lambda _code: "skip",
    *,
    demo: bool = False,
) -> ImportResult:
    """Merge an export into the database. Rolls are matched by code."""
    if data.get("format") != FORMAT:
        raise ExchangeError("Not a FilmLog export file.")
    if int(data.get("version", 0)) > VERSION:
        raise ExchangeError("This file was written by a newer FilmLog version.")
    res = ImportResult()
    counts = load_catalogue(session, data.get("catalogue") or {})
    res.catalogue_created = sum(counts.values())
    r = _Resolver(session)
    cameras = _import_cameras(session, data.get("cameras", []), res, demo)

    pending_with: list[tuple[Development, list[str]]] = []
    for rd in data.get("rolls", []):
        code = rd["code"]
        existing = session.scalar(select(Roll).where(Roll.code == code))
        if existing is not None:
            choice = on_conflict(code)
            if choice != "replace":
                res.rolls_skipped.append(code)
                continue
            session.delete(existing)
            session.flush()
            res.rolls_replaced.append(code)
        else:
            res.rolls_created.append(code)
        film = r.film(rd["film_stock"])
        if film is None:
            res.warnings.append(f"Roll {code}: unknown film {rd['film_stock']}; skipped")
            res.rolls_created = [c for c in res.rolls_created if c != code]
            continue
        roll = Roll(**_from_json(Roll, rd))
        roll.is_demo = demo
        session.add(roll)
        roll.film_stock = film
        roll.camera = cameras.get(rd.get("camera") or "")
        roll.tags = get_or_create_tags(session, rd.get("tags", []))
        roll.images = [
            RollImage(filename=i["filename"], caption=i.get("caption", ""), position=n)
            for n, i in enumerate(rd.get("images", []))
        ]
        dd = rd.get("development")
        if dd:
            dev = Development(**_from_json(Development, dd))
            _apply_chems(dev, dd, r, ("developer", "stop_chemical", "fixer", "wetting_agent"), res)
            roll.development = dev
            if dd.get("developed_with"):
                pending_with.append((dev, dd["developed_with"]))
        for pd in rd.get("prints", []):
            p = Print(**_from_json(Print, pd))
            p.is_demo = demo
            p.paper = r.paper(pd.get("paper"))
            _apply_chems(p, pd, r, ("developer", "stop_chemical", "fixer"), res)
            p.exposures = [
                PrintExposure(**_from_json(PrintExposure, e)) for e in pd.get("exposures", [])
            ]
            roll.prints.append(p)
        session.flush()

    for dev, codes in pending_with:
        dev.developed_with_rolls = [
            x for c in codes if (x := session.scalar(select(Roll).where(Roll.code == c)))
        ]
    session.flush()
    return res


def import_json(
    session: Session,
    path: Path,
    on_conflict: Callable[[str], ConflictChoice] = lambda _code: "skip",
) -> ImportResult:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExchangeError(f"Could not read {path.name}: {exc}") from exc
    return import_dict(session, data, on_conflict)
