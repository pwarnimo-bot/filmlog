# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Camera queries."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from filmlog.db.enums import CameraStatus
from filmlog.db.models import Camera, Roll


def list_cameras(session: Session, text: str = "") -> Sequence[Camera]:
    """All cameras, active ones first, then alphabetical."""
    active_first = case((Camera.status == CameraStatus.ACTIVE, 0), else_=1)
    q = select(Camera).order_by(active_first, func.lower(Camera.make), func.lower(Camera.model))
    if text.strip():
        like = f"%{text.strip()}%"
        q = q.where(
            or_(
                Camera.make.ilike(like),
                Camera.model.ilike(like),
                Camera.nickname.ilike(like),
                Camera.lens_mount.ilike(like),
                Camera.notes.ilike(like),
            )
        )
    return session.scalars(q).all()


def roll_counts(session: Session) -> dict[int, int]:
    rows = session.execute(
        select(Roll.camera_id, func.count())
        .where(Roll.camera_id.is_not(None))
        .group_by(Roll.camera_id)
    ).all()
    return {int(cid): int(n) for cid, n in rows if cid is not None}


def rolls_for(session: Session, camera_id: int) -> Sequence[Roll]:
    return session.scalars(
        select(Roll).where(Roll.camera_id == camera_id).order_by(Roll.code.desc())
    ).all()
