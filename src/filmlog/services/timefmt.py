# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parsing and formatting of durations.

Durations are stored as integer seconds and shown as ``m:ss`` (minutes may
exceed 59, e.g. a 30-minute wash is ``30:00``). Accepted input:

* ``90``           → 90 s (a bare number is seconds)
* ``1:30``         → 90 s
* ``1:02:03``      → 1 h 2 min 3 s
* ``1m30s``, ``1m 30s``, ``1 min 30 sec``, ``2m``, ``45s``, ``1h``
* ``1.5m``         → 90 s
"""

from __future__ import annotations

import re

_UNIT_RE = re.compile(
    r"^\s*(?:(?P<h>\d+(?:[.,]\d+)?)\s*h(?:ours?|rs?)?)?"
    r"\s*(?:(?P<m>\d+(?:[.,]\d+)?)\s*m(?:in(?:utes?)?|ins)?)?"
    r"\s*(?:(?P<s>\d+(?:[.,]\d+)?)\s*s(?:ec(?:onds?)?|ecs)?)?\s*$",
    re.IGNORECASE,
)


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def parse_duration(text: str) -> int | None:
    """Parse ``text`` to whole seconds. Empty → None. Raises ValueError if invalid."""
    t = text.strip()
    if not t:
        return None
    if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
        return round(_num(t))
    if ":" in t:
        parts = t.split(":")
        if len(parts) > 3 or not all(re.fullmatch(r"\d+", p.strip()) for p in parts):
            raise ValueError(f"Invalid duration: {text!r}")
        nums = [int(p) for p in parts]
        if any(n >= 60 for n in nums[1:]):
            raise ValueError(f"Seconds/minutes must be below 60: {text!r}")
        total = 0
        for n in nums:
            total = total * 60 + n
        return total
    m = _UNIT_RE.match(t)
    if m and any(m.group(g) for g in ("h", "m", "s")):
        h = _num(m.group("h")) if m.group("h") else 0.0
        mi = _num(m.group("m")) if m.group("m") else 0.0
        s = _num(m.group("s")) if m.group("s") else 0.0
        return round(h * 3600 + mi * 60 + s)
    raise ValueError(f"Invalid duration: {text!r}")


def format_duration(seconds: int | float | None) -> str:
    """Format seconds as ``m:ss``. None → empty string."""
    if seconds is None:
        return ""
    total = round(seconds)
    sign = "-" if total < 0 else ""
    total = abs(total)
    return f"{sign}{total // 60}:{total % 60:02d}"


def format_seconds(value: float | None) -> str:
    """Format a print exposure like ``12.5 s`` / ``8 s``."""
    if value is None:
        return ""
    if float(value).is_integer():
        return f"{int(value)} s"
    return f"{value:.1f} s"
