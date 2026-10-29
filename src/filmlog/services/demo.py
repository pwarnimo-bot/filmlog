# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Demo cameras / rolls / prints (Help → Load demo data / Remove demo data)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from filmlog.db.models import Camera, Print, Roll
from filmlog.seed.loader import read_seed
from filmlog.services.exchange import ImportResult, import_dict
from filmlog.services.images import delete_unreferenced, images_of_roll
from filmlog.services.rolls import prune_unused_tags


def has_demo_data(session: Session) -> bool:
    return any(
        session.scalar(select(m.id).where(m.is_demo.is_(True)).limit(1)) is not None
        for m in (Camera, Roll, Print)
    )


def load_demo(session: Session) -> ImportResult:
    """Insert demo records flagged ``is_demo``. Existing roll codes are left alone."""
    res = import_dict(session, read_seed("demo.json"), lambda _code: "skip", demo=True)
    session.commit()
    return res


@dataclass
class RemoveResult:
    rolls: int
    prints: int
    cameras: int
    cameras_kept: int


def remove_demo(session: Session) -> RemoveResult:
    """Delete demo records. Demo cameras used by your own rolls are kept (unflagged)."""
    images: list[str] = []
    rolls = session.scalars(select(Roll).where(Roll.is_demo.is_(True))).all()
    n_prints = 0
    for r in rolls:
        images += images_of_roll(r)
        n_prints += len(r.prints)
        session.delete(r)  # cascades to development, prints and exposures
    session.flush()
    removed = kept = 0
    for c in session.scalars(select(Camera).where(Camera.is_demo.is_(True))).all():
        in_use = session.scalar(select(Roll.id).where(Roll.camera_id == c.id).limit(1))
        if in_use is not None:
            c.is_demo = False
            kept += 1
        else:
            if c.photo:
                images.append(c.photo)
            session.delete(c)
            removed += 1
    prune_unused_tags(session)
    session.commit()
    delete_unreferenced(session, images)
    return RemoveResult(len(rolls), n_prints, removed, kept)
