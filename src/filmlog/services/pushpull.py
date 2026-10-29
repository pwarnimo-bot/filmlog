# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Push/pull calculation: stops = log2(EI / box ISO), rounded to ⅓ stop."""

from __future__ import annotations

import math

_THIRDS = {0: "", 1: "⅓", 2: "⅔"}


def compute_stops(ei: int | float, box_iso: int | float) -> float:
    if ei <= 0 or box_iso <= 0:
        return 0.0
    thirds = round(math.log2(ei / box_iso) * 3)
    return round(thirds / 3, 2)


def round_to_third(stops: float) -> float:
    return round(round(stops * 3) / 3, 2)


def format_stops(stops: float) -> str:
    """``1.33`` → ``1⅓``; ``-0.67`` → ``−⅔``; ``2`` → ``2``."""
    thirds = round(abs(stops) * 3)
    whole, frac = divmod(thirds, 3)
    body = (str(whole) if whole or not frac else "") + _THIRDS[frac]
    if thirds == 0:
        return "0"
    return ("+" if stops > 0 else "−") + body


def badge_text(stops: float) -> str:
    """Badge label: "Push +1", "Pull −1", "Box speed". (Translated in the UI.)"""
    if round(stops * 3) == 0:
        return "Box speed"
    return f"{'Push' if stops > 0 else 'Pull'} {format_stops(stops)}"


def badge_kind(stops: float) -> str:
    t = round(stops * 3)
    return "box" if t == 0 else ("push" if t > 0 else "pull")
