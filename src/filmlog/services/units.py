"""Unit conversions (storage is always metric / °C)."""

from __future__ import annotations

CM_PER_INCH = 2.54


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def f_to_c(f: float) -> float:
    return (f - 32) * 5 / 9


def to_display_temp(c: float | None, unit: str) -> float | None:
    if c is None:
        return None
    return round(c_to_f(c), 1) if unit == "F" else c


def from_display_temp(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    return round(f_to_c(value), 2) if unit == "F" else value


def format_temp(c: float | None, unit: str) -> str:
    v = to_display_temp(c, unit)
    if v is None:
        return ""
    text = f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{text} °{unit}"


def to_display_length(cm: float | None, unit: str) -> float | None:
    if cm is None:
        return None
    return round(cm / CM_PER_INCH, 2) if unit == "in" else cm


def from_display_length(value: float | None, unit: str) -> float | None:
    if value is None:
        return None
    return round(value * CM_PER_INCH, 2) if unit == "in" else value
