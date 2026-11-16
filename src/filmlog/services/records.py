# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deleting records together with their image files (shared by the CLI and TUI)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from filmlog.db.enums import RollStatus
from filmlog.db.models import Camera, Print, Roll
from filmlog.services import cameras as camera_service
from filmlog.services.images import delete_unreferenced, images_of_roll
from filmlog.services.rolls import prune_unused_tags


def roll_delete_question(roll: Roll) -> str:
    """Confirmation text listing what goes with the roll."""
    q = f"Delete roll {roll.code}"
    if roll.prints:
        frames = ", ".join(f"#{p.id} frame {p.frame or '?'}" for p in roll.prints)
        q += f" and its {len(roll.prints)} print(s) ({frames})"
    n = len(images_of_roll(roll))
    if n:
        q += f" and {n} image file(s)"
    return q + "? This cannot be undone."


def delete_roll(session: Session, roll: Roll) -> None:
    images = images_of_roll(roll)
    session.delete(roll)
    prune_unused_tags(session)
    session.commit()
    delete_unreferenced(session, images)


def remove_development(session: Session, roll: Roll) -> None:
    """Delete the development record; the roll goes back to *exposed*."""
    if roll.development is not None:
        session.delete(roll.development)
        roll.development = None
    roll.status = RollStatus.EXPOSED
    session.commit()


def delete_print(session: Session, p: Print) -> None:
    image = p.image
    if p in p.roll.prints:
        p.roll.prints.remove(p)
    session.delete(p)
    session.commit()
    delete_unreferenced(session, [image])


def camera_delete_question(session: Session, c: Camera) -> str:
    n = camera_service.roll_counts(session).get(c.id, 0)
    if not n:
        return f"Delete camera “{c.display_name}”?"
    return (
        f"Camera “{c.display_name}” was used for {n} roll(s); they keep their data but lose "
        "the camera link (consider status retired or sold instead). Delete it?"
    )


def delete_camera(session: Session, c: Camera) -> None:
    photo = c.photo
    session.delete(c)
    session.commit()
    delete_unreferenced(session, [photo])
