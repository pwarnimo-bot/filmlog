# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for writing form values onto ORM records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from filmlog.services.images import import_image, is_image_file


def apply_values(session: Session, obj: Any, values: dict[str, Any]) -> None:
    """Set attributes; ``*_id`` keys set the matching relationship (keeps it in sync)."""
    rels = sa_inspect(type(obj)).relationships
    for key, value in values.items():
        if key.endswith("_id") and key[:-3] in rels:
            target = rels[key[:-3]].mapper.class_
            setattr(obj, key[:-3], session.get(target, value) if value is not None else None)
        else:
            setattr(obj, key, value)


def check_image_path(text: str) -> str | None:
    """Error message for an image path typed into a form, or None if fine/empty."""
    if not text.strip():
        return None
    p = Path(text.strip()).expanduser()
    if not p.is_file():
        return "No such file."
    if not is_image_file(p):
        return "Not a supported image type (jpg, png, tif, webp …)."
    return None


def take_image(text: str) -> str | None:
    """Copy a typed image path into the images folder; return the stored name."""
    if not text.strip():
        return None
    return import_image(Path(text.strip()).expanduser())
