# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enumerations stored as plain strings in the database.

Values are stable identifiers (never shown to the user); human-readable labels
live in the UI layer so they can be translated.
"""

from __future__ import annotations

from enum import StrEnum


class FilmType(StrEnum):
    BW_NEGATIVE = "bw_negative"
    BW_REVERSAL = "bw_reversal"
    BW_CHROMOGENIC = "bw_chromogenic"
    COLOUR_NEGATIVE = "colour_negative"
    COLOUR_SLIDE = "colour_slide"
    OTHER = "other"


class ChemicalKind(StrEnum):
    FILM_DEVELOPER = "film_developer"
    PAPER_DEVELOPER = "paper_developer"
    STOP_BATH = "stop_bath"
    FIXER = "fixer"
    WETTING_AGENT = "wetting_agent"
    WASHING_AID = "washing_aid"
    TONER = "toner"
    OTHER = "other"


class ChemicalForm(StrEnum):
    LIQUID = "liquid"
    POWDER = "powder"


class PaperBase(StrEnum):
    RC = "rc"
    FB = "fb"


class ContrastType(StrEnum):
    VARIABLE = "variable"
    GRADED = "graded"


class PaperSurface(StrEnum):
    GLOSSY = "glossy"
    PEARL = "pearl"
    SATIN = "satin"
    LUSTRE = "lustre"
    SEMI_MATT = "semi_matt"
    MATT = "matt"
    OTHER = "other"


class PaperTone(StrEnum):
    NEUTRAL = "neutral"
    WARM = "warm"
    COOL = "cool"


class CameraType(StrEnum):
    SLR = "slr"
    RANGEFINDER = "rangefinder"
    TLR = "tlr"
    MEDIUM_FORMAT_SLR = "mf_slr"
    VIEWFINDER = "viewfinder"
    LARGE_FORMAT = "large_format"
    OTHER = "other"


class FilmFormat(StrEnum):
    F135 = "135"
    F120_645 = "120 6x4.5"
    F120_66 = "120 6x6"
    F120_67 = "120 6x7"
    F120_69 = "120 6x9"
    F4X5 = "4x5"
    F5X7 = "5x7"
    F8X10 = "8x10"
    OTHER = "other"


class CameraStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    SOLD = "sold"
    BROKEN = "broken"


class RollStatus(StrEnum):
    LOADED = "loaded"
    EXPOSED = "exposed"
    DEVELOPED = "developed"


class ContrastMethod(StrEnum):
    SINGLE_FILTER = "single_filter"
    SPLIT_GRADE = "split_grade"
    GRADED_PAPER = "graded_paper"
    NO_FILTER = "no_filter"


class ExposurePurpose(StrEnum):
    BASE = "base"
    SOFT = "soft"
    HARD = "hard"
    DODGE = "dodge"
    BURN = "burn"
    FLASH = "flash"


# Multigrade filter grades in display order; "none" = no filter.
FILTER_GRADES: tuple[str, ...] = (
    "00", "0", "½", "1", "1½", "2", "2½", "3", "3½", "4", "4½", "5", "none",
)  # fmt: skip

PAPER_SIZES: tuple[str, ...] = (
    "9×13 cm", "13×18 cm", "18×24 cm", "24×30 cm", "30×40 cm",
    '5×7"', '8×10"', '11×14"',
)  # fmt: skip

DEFAULT_DILUTIONS: tuple[str, ...] = (
    "stock", "1+1", "1+3", "1+9", "1+14", "1+25", "1+31", "1+50",
)  # fmt: skip
