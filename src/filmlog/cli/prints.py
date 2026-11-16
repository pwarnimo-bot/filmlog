# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""``filmlog-cli prints`` / ``print …``."""

from __future__ import annotations

import argparse
from typing import Any

from filmlog.cli.common import (
    CliError,
    Ctx,
    confirm,
    enum_help,
    parse_date,
    parse_enum,
    parse_float,
    parse_rating,
    parse_temp,
    parse_time,
    print_fields,
    print_json,
    print_table,
    stars,
)
from filmlog.db.enums import FILTER_GRADES, ChemicalKind, ContrastMethod, ExposurePurpose
from filmlog.db.models import Print, PrintExposure
from filmlog.services import lookup
from filmlog.services import prints as print_service
from filmlog.services.exchange import print_dict
from filmlog.services.images import delete_unreferenced
from filmlog.services.timefmt import format_duration, format_seconds
from filmlog.services.units import from_display_length, to_display_length

METHOD_ALIASES = {
    "single": ContrastMethod.SINGLE_FILTER,
    "split": ContrastMethod.SPLIT_GRADE,
    "graded": ContrastMethod.GRADED_PAPER,
    "none": ContrastMethod.NO_FILTER,
}
_MAIN = (ExposurePurpose.BASE, ExposurePurpose.SOFT, ExposurePurpose.HARD)

EXP_HELP = (
    "exposure GRADE:SECONDS[:PURPOSE[:NOTE]], repeatable, in order. GRADE is one of "
    + ", ".join(FILTER_GRADES)
    + " (2.5 = 2½); PURPOSE is "
    + enum_help(ExposurePurpose)
    + ". Example: --exp 00:9 --exp 5:7 --exp '5:4:burn:sky'"
)


def register(sub: argparse._SubParsersAction[Any]) -> None:
    p = sub.add_parser("prints", help="list prints", description="List prints, newest first.")
    p.add_argument("search", nargs="*", default=[], help="text in title/frame/notes/roll")
    p.add_argument("--roll", help="roll code")
    p.add_argument("--paper")
    p.add_argument("--developer", help="paper developer")
    p.add_argument("--method", help="single, split, graded, none")
    p.add_argument("--final", action="store_true", help="final prints only")
    p.add_argument("--min-rating", type=int)
    p.set_defaults(func=cmd_list)

    pr = sub.add_parser("print", help="show, add, edit, duplicate or delete a print")
    ps = pr.add_subparsers(dest="action", required=True, metavar="ACTION")

    p = ps.add_parser("show", help="show a print")
    p.add_argument("id", help="print id, e.g. 12")
    p.set_defaults(func=cmd_show)

    p = ps.add_parser(
        "add",
        help="add a print to a roll",
        description="Add a print. Paper, enlarger and chemistry are pre-filled from the last "
        "print of the roll (else the last print overall); options override them.",
    )
    p.add_argument("roll", help="roll code")
    _print_options(p)
    p.add_argument("--no-prefill", action="store_true", help="start from empty values")
    p.set_defaults(func=cmd_add)

    p = ps.add_parser("edit", help="change a print (only the given options)")
    p.add_argument("id")
    _print_options(p)
    p.set_defaults(func=cmd_edit)

    p = ps.add_parser(
        "duplicate",
        help="copy a print's settings into a new print (for the next attempt)",
        description="Copy all settings of a print into a new one dated today (not final, no "
        "rating, no image). Options change the copy.",
    )
    p.add_argument("id")
    _print_options(p)
    p.set_defaults(func=cmd_duplicate)

    p = ps.add_parser("delete", help="delete a print")
    p.add_argument("id")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask")
    p.set_defaults(func=cmd_delete)


def _print_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--frame")
    p.add_argument("--title")
    p.add_argument("--date", help="date printed (default: today)")
    p.add_argument("--paper", help="e.g. 'mg rc deluxe glossy'")
    p.add_argument("--size", help="e.g. '18×24 cm', 18x24, '8×10\"'")
    p.add_argument("--enlarger")
    p.add_argument("--enlarging-lens")
    p.add_argument("--aperture", help="e.g. f/8")
    p.add_argument("--height", help="head height (in the configured length unit)")
    p.add_argument("--method", help="contrast method: single, split, graded, none")
    p.add_argument("--exp", action="append", metavar="EXPOSURE", help=EXP_HELP)
    p.add_argument("--developer", help="paper developer")
    p.add_argument("--dilution", help="developer dilution")
    p.add_argument("--dev-time")
    p.add_argument("--temp", help="developer temperature")
    p.add_argument("--stop", help="stop bath ('water' allowed)")
    p.add_argument("--stop-time")
    p.add_argument("--fixer")
    p.add_argument("--fixer-dilution")
    p.add_argument("--fix-time")
    p.add_argument("--wash", help="wash time")
    p.add_argument("--toning", help="e.g. 'Selenium 1+9, 3 min'")
    final = p.add_mutually_exclusive_group()
    final.add_argument("--final", dest="final", action="store_true", default=None)
    final.add_argument("--work", dest="final", action="store_false", help="work print")
    p.add_argument("--rating", help="1–5")
    p.add_argument("--notes")


# --------------------------------------------------------------------------- list / show


def cmd_list(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    flt = print_service.PrintFilter(
        text=" ".join(a.search),
        paper_id=lookup.find_paper(s, a.paper).id if a.paper else None,
        developer_id=(
            lookup.find_chemical(s, a.developer, [ChemicalKind.PAPER_DEVELOPER]).id
            if a.developer
            else None
        ),
        contrast_method=(
            parse_enum(ContrastMethod, a.method, METHOD_ALIASES) if a.method else None
        ),
        final_only=a.final,
        min_rating=a.min_rating,
        roll_id=lookup.find_roll(s, a.roll).id if a.roll else None,
    )
    prints = print_service.list_prints(s, flt)
    if ctx.as_json:
        print_json(ctx, [print_dict(p) for p in prints])
        return
    rows = [
        (
            f"#{p.id}",
            p.roll.code,
            p.frame,
            p.title,
            p.date_printed,
            p.paper.display_name if p.paper else "",
            p.paper_size,
            print_service.contrast_summary(p.contrast_method, p.exposures),
            format_seconds(print_service.total_exposure(p.exposures)),
            stars(p.rating),
            "final" if p.is_final else "",
        )
        for p in prints
    ]
    headers = ("Id", "Roll", "Frame", "Title", "Date", "Paper", "Size", "Contrast", "Total",
               "Rating", "")  # fmt: skip
    print_table(ctx, headers, rows, right=(8,), empty="No prints found.")


def cmd_show(ctx: Ctx, a: argparse.Namespace) -> None:
    p = lookup.find_print(ctx.session, a.id)
    if ctx.as_json:
        print_json(ctx, print_dict(p))
        return
    show_print(ctx, p)


def _chem(c: Any, dilution: str, seconds: int | None) -> str:
    text = (c.display_name + (f" {dilution}" if dilution else "")) if c is not None else ""
    t = format_duration(seconds)
    return f"{text}, {t}" if text and t else text or t


def show_print(ctx: Ctx, p: Print) -> None:
    unit = ctx.settings.length_unit
    height = to_display_length(p.head_height_cm, unit)
    dev = _chem(p.developer, p.dev_dilution, p.dev_time_s)
    if p.dev_temperature_c is not None:
        dev += f" at {ctx.temp(p.dev_temperature_c)}"
    title = f"Print #{p.id} — roll {p.roll.code}" + (f" frame {p.frame}" if p.frame else "")
    print_fields(
        ctx,
        title + (f" “{p.title}”" if p.title else ""),
        [
            ("Date", p.date_printed),
            (
                "Paper",
                " · ".join(x for x in (p.paper.display_name if p.paper else "", p.paper_size) if x),
            ),  # fmt: skip
            ("Enlarger", " · ".join(x for x in (p.enlarger, p.enlarging_lens, p.aperture) if x)),
            ("Head height", f"{height:g} {unit}" if height is not None else ""),
            ("Contrast", print_service.contrast_summary(p.contrast_method, p.exposures)),
            ("Total", format_seconds(print_service.total_exposure(p.exposures))),
            ("Developer", dev),
            ("Stop", _chem(p.stop_chemical, "", p.stop_time_s)),
            ("Fixer", _chem(p.fixer, p.fixer_dilution, p.fix_time_s)),
            ("Wash", format_duration(p.wash_time_s)),
            ("Toning", p.toning),
            ("Final", p.is_final),
            ("Rating", stars(p.rating)),
            ("Notes", p.notes),
        ],
    )
    if p.exposures:
        ctx.print()
        rows = [
            (
                e.position + 1,
                e.purpose,
                e.filter_grade,
                format_seconds(e.seconds),
                e.aperture,
                e.note,
            )  # fmt: skip
            for e in p.exposures
        ]
        print_table(ctx, ("#", "Purpose", "Grade", "Time", "Aperture", "Note"), rows, right=(3,))


# --------------------------------------------------------------------------- editing


def parse_grade(text: str) -> str:
    t = text.strip().lower().replace(",", ".")
    if t in ("", "-", "no", "none", "nofilter"):
        return "none"
    if t.endswith(".5"):
        t = ("" if t == "0.5" else t[:-2]) + "½"
    elif t.endswith("½") and t.startswith("0") and t != "0":
        t = "½"
    if t not in FILTER_GRADES:
        raise CliError(f"Unknown filter grade “{text}”. Use one of: {', '.join(FILTER_GRADES)}.")
    return t


def parse_exposures(specs: list[str]) -> list[tuple[PrintExposure, bool]]:
    """``GRADE:SECONDS[:PURPOSE[:NOTE]]`` → exposures (+ whether a purpose was given)."""
    out = []
    for i, spec in enumerate(specs):
        parts = spec.split(":", 3)
        if len(parts) < 2:
            raise CliError(f"Exposure “{spec}”: use GRADE:SECONDS, e.g. 2.5:14 or 00:9.")
        seconds = parse_float(parts[1], "exposure time")
        if seconds is None or seconds < 0:
            raise CliError(f"Exposure “{spec}”: invalid time.")
        purpose_given = len(parts) > 2 and parts[2].strip() != ""
        purpose = parse_enum(ExposurePurpose, parts[2]) if purpose_given else ExposurePurpose.BASE
        out.append(
            (
                PrintExposure(
                    position=i,
                    filter_grade=parse_grade(parts[0]),
                    seconds=seconds,
                    purpose=purpose,
                    note=parts[3].strip() if len(parts) > 3 else "",
                    aperture="",
                ),
                purpose_given,
            )
        )
    return out


def _set_exposures(p: Print, specs: list[str], method_given: bool) -> None:
    parsed = parse_exposures(specs)
    implicit = [e for e, given in parsed if not given]
    explicit_split = any(
        e.purpose in (ExposurePurpose.SOFT, ExposurePurpose.HARD) for e, given in parsed if given
    )
    if not method_given:
        if explicit_split or len(implicit) >= 2:
            p.contrast_method = ContrastMethod.SPLIT_GRADE
        elif p.contrast_method == ContrastMethod.SPLIT_GRADE:
            p.contrast_method = ContrastMethod.SINGLE_FILTER
    if p.contrast_method == ContrastMethod.SPLIT_GRADE:
        # Exposures without a purpose: the first is the soft one, the next the hard one.
        for e, (soft_or_hard) in zip(implicit, (ExposurePurpose.SOFT, ExposurePurpose.HARD),
                                     strict=False):  # fmt: skip
            e.purpose = soft_or_hard
    p.exposures = [e for e, _ in parsed]


def _validate_exposures(p: Print) -> None:
    main = [e for e in p.exposures if e.purpose in _MAIN and (e.seconds or 0) > 0]
    if not main:
        raise CliError(
            "A print needs at least one base/soft/hard exposure with a time, "
            "e.g. --exp 2.5:14 (single filter) or --exp 00:9 --exp 5:7 (split grade)."
        )
    if p.contrast_method == ContrastMethod.SPLIT_GRADE and len(main) < 2:
        raise CliError("Split grade needs two exposures, e.g. --exp 00:9 --exp 5:7.")


def _size(text: str) -> str:
    t = text.strip().replace("x", "×").replace("X", "×").replace(" × ", "×")
    if t and t[-1].isdigit():
        t += " cm"
    return t


def _apply(ctx: Ctx, p: Print, a: argparse.Namespace) -> None:
    s = ctx.session

    def chem(ref: str, kind: ChemicalKind) -> Any:
        if ref.strip() in ("", "-", "none"):
            return None
        return lookup.find_chemical(s, ref, [kind])

    if a.frame is not None:
        p.frame = a.frame.strip()
    if a.title is not None:
        p.title = a.title.strip()
    if a.date is not None:
        p.date_printed = parse_date(a.date)
    if a.paper is not None:
        p.paper = None if a.paper.strip() in ("", "-") else lookup.find_paper(s, a.paper)
    if a.size is not None:
        p.paper_size = _size(a.size)
    if a.enlarger is not None:
        p.enlarger = a.enlarger.strip()
    if a.enlarging_lens is not None:
        p.enlarging_lens = a.enlarging_lens.strip()
    if a.aperture is not None:
        p.aperture = a.aperture.strip()
    if a.height is not None:
        p.head_height_cm = from_display_length(
            parse_float(a.height, "head height"), ctx.settings.length_unit
        )
    if a.method is not None:
        p.contrast_method = parse_enum(ContrastMethod, a.method, METHOD_ALIASES)
    if a.exp:
        _set_exposures(p, a.exp, a.method is not None)
    if a.developer is not None:
        p.developer = chem(a.developer, ChemicalKind.PAPER_DEVELOPER)
    if a.dilution is not None:
        p.dev_dilution = a.dilution.strip()
    if a.dev_time is not None:
        p.dev_time_s = parse_time(a.dev_time)
    if a.temp is not None:
        p.dev_temperature_c = parse_temp(a.temp, ctx.settings.temperature_unit)
    if a.stop is not None:
        p.stop_chemical = chem(a.stop, ChemicalKind.STOP_BATH)
    if a.stop_time is not None:
        p.stop_time_s = parse_time(a.stop_time)
    if a.fixer is not None:
        p.fixer = chem(a.fixer, ChemicalKind.FIXER)
    if a.fixer_dilution is not None:
        p.fixer_dilution = a.fixer_dilution.strip()
    if a.fix_time is not None:
        p.fix_time_s = parse_time(a.fix_time)
    if a.wash is not None:
        p.wash_time_s = parse_time(a.wash)
    if a.toning is not None:
        p.toning = a.toning.strip()
    if a.final is not None:
        p.is_final = a.final
    if a.rating is not None:
        p.rating = parse_rating(a.rating)
    if a.notes is not None:
        p.notes = a.notes
    if p.notes is None:
        p.notes = ""


def _save(ctx: Ctx, p: Print, message: str) -> None:
    for i, e in enumerate(p.exposures):
        e.position = i
    _validate_exposures(p)
    ctx.session.add(p)
    ctx.session.commit()
    if ctx.as_json:
        print_json(ctx, print_dict(p))
    else:
        ctx.note(message.format(id=p.id))
        show_print(ctx, p)


def cmd_add(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    roll = lookup.find_roll(s, a.roll)
    if a.no_prefill:
        p = Print(roll_id=roll.id, contrast_method=ContrastMethod.SINGLE_FILTER)
        p.date_printed = parse_date("today")
        p.exposures = print_service.default_exposures(p.contrast_method)
    else:
        p, src = print_service.new_print_for(s, roll)
        if src is not None:
            where = "this roll" if src.roll_id == roll.id else f"roll {src.roll.code}"
            ctx.note(f"Paper, enlarger and chemistry pre-filled from print #{src.id} ({where}).")
    p.roll = roll
    if a.method is not None and not a.exp:
        p.exposures = print_service.default_exposures(
            parse_enum(ContrastMethod, a.method, METHOD_ALIASES)
        )
    with s.no_autoflush:
        _apply(ctx, p, a)
    _save(ctx, p, "Added print #{id}.")


def cmd_edit(ctx: Ctx, a: argparse.Namespace) -> None:
    p = lookup.find_print(ctx.session, a.id)
    with ctx.session.no_autoflush:
        _apply(ctx, p, a)
    _save(ctx, p, "Saved print #{id}.")


def cmd_duplicate(ctx: Ctx, a: argparse.Namespace) -> None:
    src = lookup.find_print(ctx.session, a.id)
    p = print_service.duplicate_print(src)
    p.roll = src.roll
    with ctx.session.no_autoflush:
        _apply(ctx, p, a)
    _save(ctx, p, f"Added print #{{id}} (copy of #{src.id}).")


def cmd_delete(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    p = lookup.find_print(s, a.id)
    label = f"print #{p.id} (roll {p.roll.code}, frame {p.frame or '?'})"
    if not confirm(f"Delete {label}" + (" and its image" if p.image else "") + "?", a.yes):
        return
    image = p.image
    s.delete(p)
    s.commit()
    delete_unreferenced(s, [image])
    ctx.note(f"Deleted {label}.")
