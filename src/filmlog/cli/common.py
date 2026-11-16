# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared pieces of the command line: context, value parsing, output."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TextIO

from sqlalchemy.orm import Session

from filmlog.db.database import Database
from filmlog.services.pushpull import round_to_third
from filmlog.services.settings import Settings
from filmlog.services.timefmt import parse_duration
from filmlog.services.units import f_to_c, format_temp


class CliError(Exception):
    """A user mistake: printed without a traceback, exit status 1."""


@dataclass
class Ctx:
    session: Session
    settings: Settings
    db: Database
    as_json: bool = False
    out: TextIO = field(default_factory=lambda: sys.stdout)

    def print(self, text: str = "") -> None:
        print(text, file=self.out)

    def note(self, text: str) -> None:
        """Informational message (stderr, so ``--json`` output stays clean)."""
        print(text, file=sys.stderr)

    def temp(self, c: float | None) -> str:
        return format_temp(c, self.settings.temperature_unit)


Handler = Callable[[Ctx, argparse.Namespace], int | None]


# --------------------------------------------------------------------------- parsing

CLEAR_WORDS = ("", "-", "none", "clear")


def is_clear(text: str) -> bool:
    return text.strip().lower() in CLEAR_WORDS


def parse_date(text: str) -> dt.date | None:
    """``YYYY-MM-DD``, ``today``, ``yesterday``; ``-``/``none`` clears."""
    t = text.strip().lower()
    if is_clear(t):
        return None
    if t == "today":
        return dt.date.today()
    if t == "yesterday":
        return dt.date.today() - dt.timedelta(days=1)
    try:
        return dt.date.fromisoformat(t)
    except ValueError:
        raise CliError(f"Invalid date “{text}” (use YYYY-MM-DD, today or yesterday).") from None


def parse_time(text: str) -> int | None:
    """Duration such as ``8:30``, ``90``, ``1m30s``; ``-`` clears."""
    if is_clear(text):
        return None
    try:
        return parse_duration(text)
    except ValueError:
        raise CliError(f"Invalid time “{text}” (use m:ss, e.g. 8:30, or 90 or 1m30s).") from None


def parse_temp(text: str, unit: str) -> float | None:
    """``20``, ``20.5``, ``68F``, ``20 °C``. Bare numbers use the configured unit."""
    t = text.strip().upper().replace("°", "").replace(" ", "").replace(",", ".")
    if is_clear(t):
        return None
    if t.endswith(("C", "F")):
        unit, t = t[-1], t[:-1]
    try:
        value = float(t)
    except ValueError:
        raise CliError(f"Invalid temperature “{text}”.") from None
    return round(f_to_c(value), 2) if unit == "F" else value


_STOPS_RE = re.compile(r"^([-+−]?)\s*(\d+(?:\.\d+)?)?\s*(?:(\d)\s*/\s*3)?$")


def parse_stops(text: str) -> float:
    """``+1``, ``-1``, ``+0.33``, ``1/3``, ``-2/3``, ``1 1/3`` → stops, rounded to ⅓."""
    t = text.strip().replace("⅓", " 1/3").replace("⅔", " 2/3")
    m = _STOPS_RE.match(t)
    if not t or not m or not (m.group(2) or m.group(3)):
        raise CliError(f"Invalid push/pull “{text}” (e.g. +1, -1, +1/3, 0).")
    value = float(m.group(2) or 0) + (int(m.group(3)) / 3 if m.group(3) else 0)
    if m.group(1) in ("-", "−"):
        value = -value
    return round_to_third(value)


def parse_rating(text: str) -> int | None:
    if is_clear(text):
        return None
    if text.strip() not in {"1", "2", "3", "4", "5"}:
        raise CliError(f"Rating must be 1–5, not “{text}”.")
    return int(text)


def parse_float(text: str, what: str) -> float | None:
    if is_clear(text):
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        raise CliError(f"Invalid {what} “{text}”.") from None


def parse_int(text: str, what: str) -> int | None:
    if is_clear(text):
        return None
    try:
        return int(text)
    except ValueError:
        raise CliError(f"Invalid {what} “{text}”.") from None


def parse_enum[E: StrEnum](cls: type[E], text: str, aliases: dict[str, E] | None = None) -> E:
    t = text.strip().lower().replace("×", "x")
    if aliases and t in aliases:
        return aliases[t]
    for v in cls:
        if t in (v.value.lower(), v.name.lower()):
            return v
    choices = ", ".join(v.value for v in cls)
    raise CliError(f"Invalid value “{text}”. Choose one of: {choices}.")


def enum_help[E: StrEnum](cls: type[E]) -> str:
    return ", ".join(v.value for v in cls)


# --------------------------------------------------------------------------- confirm


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise CliError("Refusing to delete without confirmation; add --yes.")
    answer = input(f"{question} [y/N] ").strip().lower()
    return answer in ("y", "yes")


# --------------------------------------------------------------------------- output


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else ""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 1)] + "…"


def print_table(
    ctx: Ctx,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    right: Sequence[int] = (),
    empty: str = "Nothing found.",
) -> None:
    """Aligned text table, squeezed to the terminal width (widest columns clipped)."""
    if not rows:
        ctx.note(empty)
        return
    cells = [[fmt(c).replace("\n", " ") for c in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) for i, h in enumerate(headers)]
    total = shutil.get_terminal_size((120, 24)).columns if ctx.out.isatty() else 10_000
    gap = 2
    while sum(widths) + gap * (len(widths) - 1) > total and max(widths) > 8:
        widths[widths.index(max(widths))] -= 1

    def line(values: Sequence[str]) -> str:
        parts = []
        for i, v in enumerate(values):
            v = _clip(v, widths[i])
            parts.append(v.rjust(widths[i]) if i in right else v.ljust(widths[i]))
        return (" " * gap).join(parts).rstrip()

    ctx.print(line(list(headers)))
    ctx.print(line(["─" * w for w in widths]))
    for r in cells:
        ctx.print(line(r))


def print_fields(ctx: Ctx, title: str, fields: Sequence[tuple[str, Any]]) -> None:
    """A heading followed by ``label: value`` lines (empty values skipped)."""
    ctx.print(title)
    shown = [(k, fmt(v)) for k, v in fields if fmt(v) != ""]
    if not shown:
        return
    width = max(len(k) for k, _ in shown)
    for k, v in shown:
        lines = v.splitlines() or [""]
        ctx.print(f"  {k.ljust(width)}  {lines[0]}")
        for extra in lines[1:]:
            ctx.print(f"  {' ' * width}  {extra}")


def print_json(ctx: Ctx, data: Any) -> None:
    json.dump(data, ctx.out, indent=2, ensure_ascii=False, default=fmt)
    ctx.print()


def stars(rating: int | None) -> str:
    return "★" * rating + "☆" * (5 - rating) if rating else ""
