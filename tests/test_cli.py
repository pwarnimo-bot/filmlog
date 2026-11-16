# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Command line (``filmlog-cli``) and the lookup service it uses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from filmlog.cli import main
from filmlog.cli.common import CliError, parse_stops, parse_temp, parse_time
from filmlog.cli.prints import parse_grade
from filmlog.services import lookup


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def run_json(capsys: pytest.CaptureFixture[str], *args: str) -> object:
    code, out, err = run(capsys, "--json", *args)
    assert code == 0, err
    return json.loads(out)


# --------------------------------------------------------------------------- parsing


def test_value_parsers() -> None:
    assert parse_stops("+1") == 1.0
    assert parse_stops("-1/3") == -0.33
    assert parse_stops("1 1/3") == 1.33
    assert parse_stops("−2") == -2.0
    assert parse_time("8:30") == 510
    assert parse_time("-") is None
    assert parse_temp("68F", "C") == 20.0
    assert parse_temp("20", "C") == 20.0
    assert parse_temp("20.5 °C", "F") == 20.5
    assert parse_grade("2.5") == "2½"
    assert parse_grade("0.5") == "½"
    assert parse_grade("00") == "00"
    with pytest.raises(CliError):
        parse_stops("lots")
    with pytest.raises(CliError):
        parse_grade("7")


def test_lookup_prefers_whole_words(session: Session) -> None:
    assert lookup.find_film(session, "pan 100").display_name == "Kentmere Pan 100"
    assert lookup.find_film(session, "fp4").name == "FP4 Plus"
    # Aliases are searched too.
    assert lookup.find_film(session, "t-max 400").name == "Ektapan 400"
    with pytest.raises(lookup.LookupError_) as exc:
        lookup.find_film(session, "pan")
    assert len(exc.value.candidates) > 1
    film = lookup.find_film(session, "hp5")
    assert lookup.find_film(session, f"#{film.id}") is film


# --------------------------------------------------------------------------- commands


def test_info_and_path(capsys: pytest.CaptureFixture[str], isolated_paths: Path) -> None:
    code, out, _ = run(capsys, "path")
    assert code == 0
    assert out.strip() == str(isolated_paths / "data" / "filmlog.db")
    info = run_json(capsys, "info")
    assert isinstance(info, dict)
    assert info["rolls"] == 0


def test_roll_lifecycle(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "roll", "add", "--film", "hp5", "--ei", "1600", "--title", "Night")
    assert code == 0, err
    roll = run_json(capsys, "roll", "show", "2026-001")
    assert isinstance(roll, dict)
    assert roll["shot_iso"] == 1600
    assert roll["push_pull_stops"] == 2.0
    assert roll["status"] == "loaded"

    # A development needs a time.
    code, _, err = run(capsys, "roll", "develop", "2026-001", "--developer", "microphen")
    assert code == 1 and "time is required" in err

    code, _, err = run(capsys, "roll", "develop", "2026-001", "--developer", "microphen",
                       "--dilution", "stock", "--time", "16:30", "--stop", "water")  # fmt: skip
    assert code == 0, err
    roll = run_json(capsys, "roll", "show", "2026-001")
    assert isinstance(roll, dict)
    assert roll["status"] == "developed"
    assert roll["development"]["dev_time_s"] == 990
    assert roll["development"]["stop_chemical"]["name"] == "Water"

    # The next roll of the same film is pre-filled from this one.
    run(capsys, "roll", "add", "--film", "hp5", "--ei", "1600", "--status", "exposed")
    code, _, err = run(capsys, "roll", "develop", "2026-002", "--rating", "4")
    assert code == 0, err
    assert "Pre-filled from roll 2026-001" in err

    # Status can't leave "developed" while a development exists.
    code, _, err = run(capsys, "roll", "edit", "2026-002", "--status", "exposed")
    assert code == 1 and "undevelop" in err
    assert run(capsys, "roll", "undevelop", "2026-002", "--yes")[0] == 0

    recipes = run_json(capsys, "recipes", "hp5", "--developer", "microphen")
    assert isinstance(recipes, list) and [r["roll"] for r in recipes] == ["2026-001"]

    listed = run_json(capsys, "rolls", "--status", "exposed")
    assert isinstance(listed, list) and [r["code"] for r in listed] == ["2026-002"]


def test_print_add_split_grade_and_duplicate(capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "roll", "add", "--film", "fp4", "--code", "R1")
    code, _, err = run(
        capsys, "print", "add", "R1", "--frame", "14", "--paper", "rc deluxe glossy",
        "--size", "18x24", "--exp", "00:9", "--exp", "5:7", "--exp", "5:4:burn:sky",
    )  # fmt: skip
    assert code == 0, err
    p = run_json(capsys, "print", "show", "1")
    assert isinstance(p, dict)
    assert p["contrast_method"] == "split_grade"
    assert p["paper_size"] == "18×24 cm"
    assert [(e["filter_grade"], e["purpose"]) for e in p["exposures"]] == [
        ("00", "soft"), ("5", "hard"), ("5", "burn"),
    ]  # fmt: skip

    code, _, err = run(capsys, "print", "duplicate", "1", "--exp", "2.5:14", "--final")
    assert code == 0, err
    dup = run_json(capsys, "print", "show", "2")
    assert isinstance(dup, dict)
    assert dup["contrast_method"] == "single_filter"
    assert dup["is_final"] is True
    assert dup["paper"]["name"] == "Multigrade RC Deluxe"

    # No exposure time → refused, nothing saved.
    code, _, err = run(capsys, "print", "add", "R1", "--frame", "3", "--no-prefill")
    assert code == 1 and "exposure" in err
    assert len(run_json(capsys, "prints", "--roll", "R1")) == 2  # type: ignore[arg-type]


def test_delete_needs_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    run(capsys, "roll", "add", "--film", "fp4", "--code", "R1")
    code, _, err = run(capsys, "roll", "delete", "R1")
    assert code == 1 and "--yes" in err
    assert run(capsys, "roll", "delete", "R1", "--yes")[0] == 0
    code, _, err = run(capsys, "roll", "show", "R1")
    assert code == 1 and "No roll" in err


def test_cameras_catalogue_and_demo(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, _, err = run(capsys, "camera", "add", "--make", "Nikon", "--model", "FM2",
                       "--format", "135", "--lenses", "Nikkor 50mm f/1.8")  # fmt: skip
    assert code == 0, err
    run(capsys, "roll", "add", "--film", "fp4", "--camera", "fm2", "--code", "R1")
    roll = run_json(capsys, "roll", "show", "R1")
    assert isinstance(roll, dict)
    assert roll["camera"] == "Nikon FM2" and roll["lens"] == "Nikkor 50mm f/1.8"

    stops = run_json(capsys, "chemicals", "--kind", "stop")
    assert isinstance(stops, list) and stops[0]["name"] == "Water"
    assert run(capsys, "film", "add", "--maker", "ilford", "--name", "Test", "--iso", "64")[0] == 0
    # Same manufacturer regardless of capitalisation → duplicate.
    assert run(capsys, "film", "add", "--maker", "Ilford", "--name", "Test", "--iso", "64")[0] == 1

    assert run(capsys, "demo", "load")[0] == 0
    assert len(run_json(capsys, "rolls")) == 10  # type: ignore[arg-type]
    assert run(capsys, "demo", "remove")[0] == 0
    assert [r["code"] for r in run_json(capsys, "rolls")] == ["R1"]  # type: ignore[union-attr]

    out = tmp_path / "export.json"
    assert run(capsys, "export", "json", str(out))[0] == 0
    assert json.loads(out.read_text())["format"] == "filmlog-export"
    code, stdout, _ = run(capsys, "import", str(out))
    assert code == 0 and "1 skipped" in stdout
