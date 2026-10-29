# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import pytest

from filmlog.services.pushpull import badge_kind, badge_text, compute_stops, format_stops
from filmlog.services.timefmt import format_duration, format_seconds, parse_duration
from filmlog.services.units import c_to_f, format_temp, from_display_temp, to_display_length


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("90", 90),
        ("1:30", 90),
        ("1m30s", 90),
        ("1m 30s", 90),
        ("1 min 30 sec", 90),
        ("2m", 120),
        ("45s", 45),
        ("8:30", 510),
        ("30:00", 1800),
        ("1:02:03", 3723),
        ("1h", 3600),
        ("1.5m", 90),
        ("  13:00 ", 780),
    ],
)
def test_parse_duration(text: str, seconds: int) -> None:
    assert parse_duration(text) == seconds


def test_parse_duration_empty_is_none() -> None:
    assert parse_duration("") is None
    assert parse_duration("   ") is None


@pytest.mark.parametrize("text", ["abc", "1:75", "1::2", "m", "1:2:3:4", "5x"])
def test_parse_duration_invalid(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(text)


def test_format_duration() -> None:
    assert format_duration(90) == "1:30"
    assert format_duration(510) == "8:30"
    assert format_duration(5) == "0:05"
    assert format_duration(1800) == "30:00"
    assert format_duration(None) == ""
    assert parse_duration(format_duration(765)) == 765


def test_format_seconds() -> None:
    assert format_seconds(8) == "8 s"
    assert format_seconds(12.5) == "12.5 s"


@pytest.mark.parametrize(
    ("ei", "box", "stops"),
    [
        (400, 400, 0.0),
        (800, 400, 1.0),
        (1600, 400, 2.0),
        (200, 400, -1.0),
        (500, 400, 0.33),
        (640, 400, 0.67),
        (3200, 400, 3.0),
        (1000, 3200, -1.67),
        (100, 125, -0.33),
    ],
)
def test_compute_stops(ei: int, box: int, stops: float) -> None:
    assert compute_stops(ei, box) == stops


def test_badges() -> None:
    assert badge_text(0) == "Box speed"
    assert badge_text(2) == "Push +2"
    assert badge_text(-1) == "Pull −1"
    assert badge_text(0.33) == "Push +⅓"
    assert badge_text(1.67) == "Push +1⅔"
    assert format_stops(-0.67) == "−⅔"
    assert badge_kind(0.33) == "push"
    assert badge_kind(-1) == "pull"
    assert badge_kind(0.01) == "box"


def test_units() -> None:
    assert c_to_f(20) == 68
    assert format_temp(20.0, "C") == "20 °C"
    assert format_temp(20.0, "F") == "68 °F"
    assert from_display_temp(68.0, "F") == 20.0
    assert to_display_length(25.4, "in") == 10.0
