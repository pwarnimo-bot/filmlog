# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Find records from short, human-typed references (used by the command line).

A reference is either a numeric id (``#12`` or ``12``) or free text. Text matches
when every word appears in the record's display name (case-insensitive), so
``fp4`` finds "Ilford FP4 Plus 125" and ``fm2`` finds "Nikon FM2". An exact
display-name match wins over partial matches.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from filmlog.db.enums import ChemicalKind
from filmlog.db.models import Camera, Chemical, FilmStock, Paper, Print, Roll
from filmlog.services import cameras as camera_service
from filmlog.services import catalogue


class LookupError_(LookupError):  # noqa: N801 - avoid shadowing the builtin
    """No match, or more than one match, for a reference."""

    def __init__(self, what: str, ref: str, candidates: Sequence[str] = ()) -> None:
        self.what = what
        self.ref = ref
        self.candidates = list(candidates)
        if candidates:
            listing = "\n".join(f"  {c}" for c in self.candidates[:15])
            more = "\n  …" if len(self.candidates) > 15 else ""
            msg = f"“{ref}” matches several {what}s:\n{listing}{more}"
        else:
            msg = f"No {what} matches “{ref}”."
        super().__init__(msg)


def _as_id(ref: str) -> int | None:
    t = ref.strip().lstrip("#")
    return int(t) if t.isdigit() else None


def _words(text: str) -> list[str]:
    return text.lower().replace("-", " ").split()


def match_items[T](
    items: Sequence[T],
    ref: str,
    name: Callable[[T], str],
    extra: Callable[[T], str] = lambda _x: "",
) -> list[T]:
    """Items whose name (+ ``extra`` text) contains every word of ``ref``."""
    want = ref.strip().lower()
    exact = [i for i in items if name(i).lower() == want]
    if exact:
        return exact
    words = _words(ref)
    whole: list[T] = []
    partial: list[T] = []
    for i in items:
        hay_words = _words(name(i) + " " + extra(i))
        hay = " ".join(hay_words)
        if all(w in hay_words for w in words):
            whole.append(i)
        elif all(w in hay for w in words):
            partial.append(i)
    # Whole-word hits win: "pan 100" → Kentmere Pan 100, not Fomapan 100.
    return whole or partial


def _pick[T](
    what: str,
    ref: str,
    items: Sequence[T],
    name: Callable[[T], str],
    extra: Callable[[T], str] = lambda _x: "",
) -> T:
    oid = _as_id(ref)
    if oid is not None:
        for i in items:
            if getattr(i, "id", None) == oid:
                return i
    hits = match_items(items, ref, name, extra)
    if len(hits) == 1:
        return hits[0]
    raise LookupError_(what, ref, [f"#{getattr(h, 'id', '?')}  {name(h)}" for h in hits])


def find_film(session: Session, ref: str) -> FilmStock:
    return _pick(
        "film stock",
        ref,
        catalogue.film_stocks(session),
        lambda f: f.display_name,
        lambda f: f.aliases,
    )


def find_camera(session: Session, ref: str) -> Camera:
    return _pick(
        "camera",
        ref,
        camera_service.list_cameras(session),
        lambda c: c.display_name,
        lambda c: f"{c.make} {c.model} {c.nickname}",
    )


def find_chemical(session: Session, ref: str, kinds: Sequence[ChemicalKind] = ()) -> Chemical:
    what = "chemical"
    if len(kinds) == 1:
        what = kinds[0].value.replace("_", " ")
    return _pick(what, ref, catalogue.chemicals(session, kinds or None), lambda c: c.display_name)


def find_paper(session: Session, ref: str) -> Paper:
    return _pick("paper", ref, catalogue.papers(session), lambda p: p.display_name)


def find_roll(session: Session, code: str) -> Roll:
    """Rolls are referenced by their code (case-insensitive)."""
    roll = session.scalar(select(Roll).where(func.lower(Roll.code) == code.strip().lower()))
    if roll is None:
        raise LookupError_("roll", code)
    return roll


def find_print(session: Session, ref: str) -> Print:
    """Prints are referenced by id (``12`` or ``#12``)."""
    pid = _as_id(ref)
    p = session.get(Print, pid) if pid is not None else None
    if p is None:
        raise LookupError_("print", ref)
    return p


def describe(obj: Any) -> str:
    return str(getattr(obj, "display_name", obj))
