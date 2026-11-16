# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""``filmlog-cli roll …`` / ``rolls`` / ``recipes``."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

from filmlog.cli.common import (
    CliError,
    Ctx,
    confirm,
    enum_help,
    parse_date,
    parse_enum,
    parse_int,
    parse_rating,
    parse_stops,
    parse_temp,
    parse_time,
    print_fields,
    print_json,
    print_table,
    stars,
)
from filmlog.db.enums import ChemicalKind, FilmFormat, RollStatus
from filmlog.db.models import Development, Roll
from filmlog.services import development as dev_service
from filmlog.services import lookup
from filmlog.services import rolls as roll_service
from filmlog.services.exchange import roll_dict
from filmlog.services.images import delete_unreferenced, images_of_roll
from filmlog.services.prints import contrast_summary, total_exposure
from filmlog.services.pushpull import badge_text, compute_stops
from filmlog.services.timefmt import format_duration, format_seconds

PREFILL_REASONS = {
    "same_film_ei": "same film and EI",
    "same_film": "same film",
    "last": "last development",
}


def register(sub: argparse._SubParsersAction[Any]) -> None:
    p = sub.add_parser("rolls", help="list rolls", description="List rolls (newest code first).")
    p.add_argument("search", nargs="*", default=[], help="text in code/title/notes/film/camera")
    p.add_argument("--status", help=enum_help(RollStatus))
    p.add_argument("--film", help="film stock (name or #id)")
    p.add_argument("--camera", help="camera (name or #id)")
    p.add_argument("--developer", help="film developer (name or #id)")
    p.add_argument("--year", type=int)
    p.add_argument("--tag")
    p.set_defaults(func=cmd_list)

    roll = sub.add_parser("roll", help="show, add, edit, develop or delete a roll")
    rs = roll.add_subparsers(dest="action", required=True, metavar="ACTION")

    p = rs.add_parser("show", help="show a roll with its development and prints")
    p.add_argument("code")
    p.set_defaults(func=cmd_show)

    p = rs.add_parser("add", help="add a roll", description="Add a roll. Only --film is required.")
    p.add_argument("--code", help="default: next free YYYY-NNN")
    _roll_options(p, adding=True)
    p.set_defaults(func=cmd_add)

    p = rs.add_parser(
        "edit",
        help="change fields of a roll",
        description="Change a roll. Only the options you give are changed; '-' clears a field.",
    )
    p.add_argument("code")
    p.add_argument("--new-code", help="rename the roll")
    _roll_options(p, adding=False)
    p.set_defaults(func=cmd_edit)

    p = rs.add_parser(
        "develop",
        help="record (or change) the development of a roll",
        description="Mark a roll as developed. A new development is pre-filled from the most "
        "recent development of the same film at the same EI (then same film, then the last "
        "one); options override those values. On an already developed roll only the given "
        "options are changed. Times as m:ss (8:30), 90 or 1m30s.",
    )
    p.add_argument("code")
    _development_options(p)
    p.set_defaults(func=cmd_develop)

    p = rs.add_parser("undevelop", help="delete the development record (status → exposed)")
    p.add_argument("code")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask")
    p.set_defaults(func=cmd_undevelop)

    p = rs.add_parser("delete", help="delete a roll with its development, prints and images")
    p.add_argument("code")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask")
    p.set_defaults(func=cmd_delete)

    p = rs.add_parser("next-code", help="print the next free YYYY-NNN code")
    p.add_argument("--year", type=int)
    p.set_defaults(func=cmd_next_code)

    p = rs.add_parser("card", help="export the printable darkroom card (PDF or HTML)")
    p.add_argument("code")
    p.add_argument("output", help="file name ending in .pdf or .html")
    p.set_defaults(func=cmd_card)

    p = sub.add_parser(
        "recipes",
        help="past developments of a film (what worked before)",
        description="Previous developments of a film stock, optionally only with one developer "
        "and dilution. Published times are starting points, not gospel.",
    )
    p.add_argument("film")
    p.add_argument("--developer")
    p.add_argument("--dilution")
    p.set_defaults(func=cmd_recipes)


def _roll_options(p: argparse.ArgumentParser, *, adding: bool) -> None:
    p.add_argument("--film", required=adding, help="film stock, e.g. 'hp5' or '#3'")
    p.add_argument("--ei", type=int, help="exposure index shot at (default: box ISO)")
    p.add_argument("--push", help="push/pull stops, e.g. +1, -1, +1/3 (default: from EI)")
    p.add_argument("--camera", help="camera, e.g. 'fm2' ('-' for none)")
    p.add_argument("--lens")
    p.add_argument("--format", help=enum_help(FilmFormat) + " (default: the camera's)")
    p.add_argument("--exposures", help="number of frames")
    p.add_argument("--title")
    p.add_argument("--location", help="subject / location")
    p.add_argument("--loaded", help="date loaded (YYYY-MM-DD, today)")
    p.add_argument("--finished", help="date finished")
    p.add_argument("--expiry", help="film expiry date")
    p.add_argument("--status", help=enum_help(RollStatus))
    p.add_argument("--tags", help="comma-separated, replaces the existing tags")
    p.add_argument("--notes")


def _development_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--date", help="date developed (default: today)")
    p.add_argument("--developer", help="film developer, e.g. 'id-11'")
    p.add_argument("--dilution", help="e.g. stock, 1+1")
    p.add_argument("--time", help="development time, e.g. 8:30")
    p.add_argument("--temp", help="temperature, e.g. 20 or 68F")
    p.add_argument("--agitation", help="agitation text or preset name")
    p.add_argument("--presoak")
    p.add_argument("--stop", help="stop bath ('water' allowed)")
    p.add_argument("--stop-time")
    p.add_argument("--rinse", help="rinse time")
    p.add_argument("--fixer")
    p.add_argument("--fixer-dilution")
    p.add_argument("--fix-time")
    p.add_argument("--wash", help="wash time")
    p.add_argument("--wash-method")
    p.add_argument("--wetting", help="wetting agent")
    p.add_argument("--wetting-time")
    p.add_argument("--tank")
    p.add_argument("--with", dest="with_rolls", help="codes of rolls developed in the same tank")
    p.add_argument("--rating", help="negative quality 1–5")
    p.add_argument("--notes")
    p.add_argument("--no-prefill", action="store_true", help="start from empty values")


# --------------------------------------------------------------------------- list / show


def cmd_list(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    tag_id = None
    if a.tag:
        tags = [t for t in roll_service.all_tags(s) if t.name.lower() == a.tag.lower()]
        if not tags:
            raise CliError(f"No tag “{a.tag}”.")
        tag_id = tags[0].id
    flt = roll_service.RollFilter(
        text=" ".join(a.search),
        status=parse_enum(RollStatus, a.status) if a.status else None,
        film_stock_id=lookup.find_film(s, a.film).id if a.film else None,
        camera_id=lookup.find_camera(s, a.camera).id if a.camera else None,
        developer_id=(
            lookup.find_chemical(s, a.developer, [ChemicalKind.FILM_DEVELOPER]).id
            if a.developer
            else None
        ),
        year=a.year,
        tag_id=tag_id,
    )
    rolls = roll_service.list_rolls(s, flt)
    if ctx.as_json:
        print_json(ctx, [roll_dict(r) for r in rolls])
        return
    rows = [
        (
            r.code,
            r.status,
            r.title,
            r.film_stock.display_name,
            _ei(r),
            r.camera.display_name if r.camera else "",
            r.development.date_developed if r.development else "",
            len(r.prints) or "",
        )
        for r in rolls
    ]
    headers = ("Code", "Status", "Title", "Film", "EI", "Camera", "Developed", "Prints")
    print_table(ctx, headers, rows, right=(7,), empty="No rolls found.")


def _ei(r: Roll) -> str:
    badge = badge_text(r.push_pull_stops)
    return f"{r.shot_iso}" if badge == "Box speed" else f"{r.shot_iso} ({badge})"


def cmd_show(ctx: Ctx, a: argparse.Namespace) -> None:
    r = lookup.find_roll(ctx.session, a.code)
    if ctx.as_json:
        print_json(ctx, roll_dict(r))
        return
    show_roll(ctx, r)


def show_roll(ctx: Ctx, r: Roll) -> None:
    expired = " (expired film)" if r.is_expired_film else ""
    print_fields(
        ctx,
        f"Roll {r.code}" + (f" — {r.title}" if r.title else ""),
        [
            ("Status", r.status),
            ("Film", r.film_stock.display_name),
            ("EI", f"{r.shot_iso} · {badge_text(r.push_pull_stops)}"),
            ("Camera", r.camera.display_name if r.camera else ""),
            ("Lens", r.lens),
            ("Format", r.format),
            ("Exposures", r.exposures),
            ("Subject", r.subject_location),
            ("Loaded", r.date_loaded),
            ("Finished", r.date_finished),
            ("Film expiry", f"{r.film_expiry}{expired}" if r.film_expiry else ""),
            ("Tags", ", ".join(t.name for t in r.tags)),
            ("Notes", r.notes),
        ],
    )
    if r.development is not None:
        ctx.print()
        show_development(ctx, r.development)
    elif r.status != RollStatus.DEVELOPED:
        ctx.print()
        ctx.print(f"Not developed yet — record it with: filmlog-cli roll develop {r.code}")
    if r.prints:
        ctx.print()
        ctx.print("Prints")
        rows = [
            (
                f"#{p.id}",
                p.frame,
                p.date_printed,
                p.paper.display_name if p.paper else "",
                p.paper_size,
                contrast_summary(p.contrast_method, p.exposures),
                format_seconds(total_exposure(p.exposures)),
                stars(p.rating),
                "final" if p.is_final else "",
            )
            for p in r.prints
        ]
        headers = ("Id", "Frame", "Date", "Paper", "Size", "Contrast", "Total", "Rating", "")
        print_table(ctx, headers, rows, right=(6,))


def _chem(c: Any, dilution: str = "") -> str:
    if c is None:
        return ""
    return c.display_name + (f" {dilution}" if dilution else "")


def _step(c: Any, dilution: str, seconds: int | None) -> str:
    text = _chem(c, dilution)
    t = format_duration(seconds)
    return f"{text}, {t}" if text and t else text or t


def show_development(ctx: Ctx, d: Development) -> None:
    print_fields(
        ctx,
        "Development",
        [
            ("Date", d.date_developed),
            ("Developer", _chem(d.developer, d.dilution)),
            ("Time", f"{format_duration(d.dev_time_s)} at {ctx.temp(d.temperature_c)}"),
            ("Agitation", d.agitation),
            ("Presoak", format_duration(d.presoak_s)),
            ("Stop", _step(d.stop_chemical, "", d.stop_time_s)),
            ("Rinse", format_duration(d.rinse_time_s)),
            ("Fixer", _step(d.fixer, d.fixer_dilution, d.fix_time_s)),
            ("Wash", ", ".join(x for x in (format_duration(d.wash_time_s), d.wash_method) if x)),
            ("Wetting agent", _step(d.wetting_agent, "", d.wetting_time_s)),
            ("Tank", d.tank),
            ("Developed with", ", ".join(r.code for r in d.developed_with_rolls)),
            ("Result", stars(d.result_rating)),
            ("Notes", d.notes),
        ],
    )


# --------------------------------------------------------------------------- add / edit


def _apply_roll_options(ctx: Ctx, r: Roll, a: argparse.Namespace, *, adding: bool) -> None:
    s = ctx.session
    old_film = r.film_stock if not adding else None
    if a.film is not None:
        r.film_stock = lookup.find_film(s, a.film)
    film = r.film_stock
    camera_changed = False
    if a.camera is not None:
        new_cam = None if a.camera.strip() in ("", "-") else lookup.find_camera(s, a.camera)
        camera_changed = new_cam is not r.camera or adding
        r.camera = new_cam
    if a.ei is not None:
        r.shot_iso = a.ei
    elif adding or (
        old_film is not None and old_film is not film and r.shot_iso == old_film.box_iso
    ):
        r.shot_iso = film.box_iso  # follow the film's box speed unless an EI was chosen
    if a.push is not None:
        r.push_pull_stops = parse_stops(a.push)
    elif adding or a.ei is not None or a.film is not None:
        r.push_pull_stops = compute_stops(r.shot_iso, film.box_iso)
    if a.format is not None:
        r.format = parse_enum(FilmFormat, a.format)
    elif camera_changed and r.camera is not None:
        r.format = r.camera.format
    if a.lens is not None:
        r.lens = a.lens.strip()
    elif camera_changed and r.camera is not None and len(r.camera.lens_list) == 1:
        r.lens = r.camera.lens_list[0]
    if a.exposures is not None:
        r.exposures = parse_int(a.exposures, "number of exposures")
    if a.title is not None:
        r.title = a.title.strip()
    if a.location is not None:
        r.subject_location = a.location.strip()
    if a.loaded is not None:
        r.date_loaded = parse_date(a.loaded)
    if a.finished is not None:
        r.date_finished = parse_date(a.finished)
    if a.expiry is not None:
        r.film_expiry = parse_date(a.expiry)
    if a.status is not None:
        status = parse_enum(RollStatus, a.status)
        if r.development is not None and status != RollStatus.DEVELOPED:
            raise CliError(
                f"Roll {r.code} has a development record; remove it first with "
                f"'filmlog-cli roll undevelop {r.code}'."
            )
        r.status = status
    if a.tags is not None:
        r.tags = roll_service.get_or_create_tags(s, roll_service.parse_tags(a.tags))
    if a.notes is not None:
        r.notes = a.notes


def cmd_add(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    code = (a.code or roll_service.suggest_code(s)).strip()
    if roll_service.code_exists(s, code):
        raise CliError(f"A roll with code {code} already exists.")
    r = Roll(code=code, status=RollStatus.LOADED, notes="")
    with s.no_autoflush:
        _apply_roll_options(ctx, r, a, adding=True)
    s.add(r)
    s.commit()
    _done(ctx, r, f"Added roll {r.code}.")


def cmd_edit(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    r = lookup.find_roll(s, a.code)
    if a.new_code is not None:
        code = a.new_code.strip()
        if not code:
            raise CliError("The code cannot be empty.")
        if roll_service.code_exists(s, code, exclude_id=r.id):
            raise CliError(f"Another roll already uses code {code}.")
        r.code = code
    with s.no_autoflush:
        _apply_roll_options(ctx, r, a, adding=False)
    roll_service.prune_unused_tags(s)
    s.commit()
    _done(ctx, r, f"Saved roll {r.code}.")


def _done(ctx: Ctx, r: Roll, message: str) -> None:
    if ctx.as_json:
        print_json(ctx, roll_dict(r))
    else:
        ctx.note(message)
        show_roll(ctx, r)


# --------------------------------------------------------------------------- develop


def cmd_develop(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    r = lookup.find_roll(s, a.code)
    dev = r.development
    is_new = dev is None
    if dev is None:
        if a.no_prefill:
            dev, pre = Development(date_developed=dt.date.today(), temperature_c=20.0), None
        else:
            dev, pre = dev_service.new_development_for(s, r)
        if pre is not None:
            ctx.note(
                f"Pre-filled from roll {pre.source.roll.code} "
                f"({PREFILL_REASONS.get(pre.reason, pre.reason)}) — check the values."
            )
    with s.no_autoflush:
        _apply_development_options(ctx, dev, a, r)
    if not dev.dev_time_s:
        raise CliError("A development time is required: add --time, e.g. --time 8:30.")
    if is_new:
        dev_service.mark_developed(r, dev)
    s.commit()
    _done(ctx, r, f"{'Recorded' if is_new else 'Updated'} the development of roll {r.code}.")


def _apply_development_options(ctx: Ctx, d: Development, a: argparse.Namespace, r: Roll) -> None:
    s = ctx.session
    unit = ctx.settings.temperature_unit

    def chem(ref: str, kind: ChemicalKind) -> Any:
        if ref.strip() in ("", "-", "none"):
            return None
        return lookup.find_chemical(s, ref, [kind])

    if a.date is not None:
        d.date_developed = parse_date(a.date)
    if a.developer is not None:
        d.developer = chem(a.developer, ChemicalKind.FILM_DEVELOPER)
    if a.dilution is not None:
        d.dilution = a.dilution.strip()
    if a.time is not None:
        d.dev_time_s = parse_time(a.time)  # type: ignore[assignment]
    if a.temp is not None:
        temp = parse_temp(a.temp, unit)
        d.temperature_c = 20.0 if temp is None else temp
    if a.agitation is not None:
        d.agitation = _agitation(ctx, a.agitation)
    if a.presoak is not None:
        d.presoak_s = parse_time(a.presoak)
    if a.stop is not None:
        d.stop_chemical = chem(a.stop, ChemicalKind.STOP_BATH)
    if a.stop_time is not None:
        d.stop_time_s = parse_time(a.stop_time)
    if a.rinse is not None:
        d.rinse_time_s = parse_time(a.rinse)
    if a.fixer is not None:
        d.fixer = chem(a.fixer, ChemicalKind.FIXER)
    if a.fixer_dilution is not None:
        d.fixer_dilution = a.fixer_dilution.strip()
    if a.fix_time is not None:
        d.fix_time_s = parse_time(a.fix_time)
    if a.wash is not None:
        d.wash_time_s = parse_time(a.wash)
    if a.wash_method is not None:
        d.wash_method = a.wash_method.strip()
    if a.wetting is not None:
        d.wetting_agent = chem(a.wetting, ChemicalKind.WETTING_AGENT)
    if a.wetting_time is not None:
        d.wetting_time_s = parse_time(a.wetting_time)
    if a.tank is not None:
        d.tank = a.tank.strip()
    if a.with_rolls is not None:
        others = []
        for code in roll_service.parse_tags(a.with_rolls):
            other = lookup.find_roll(s, code)
            if other is not r:
                others.append(other)
        d.developed_with_rolls = others
    if a.rating is not None:
        d.result_rating = parse_rating(a.rating)
    if a.notes is not None:
        d.notes = a.notes
    elif d.notes is None:
        d.notes = ""


def _agitation(ctx: Ctx, text: str) -> str:
    """A preset name (or unique part of it) expands to the preset text."""
    from filmlog.services.catalogue import agitation_presets

    presets = agitation_presets(ctx.session)
    hits = lookup.match_items(presets, text, lambda p: p.name)
    if len(hits) == 1 and len(text.split()) <= 3:
        return hits[0].text
    return text.strip()


def cmd_undevelop(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    r = lookup.find_roll(s, a.code)
    if r.development is None:
        raise CliError(f"Roll {r.code} has no development record.")
    if not confirm(f"Delete the development record of roll {r.code}?", a.yes):
        return
    s.delete(r.development)
    r.development = None
    r.status = RollStatus.EXPOSED
    s.commit()
    ctx.note(f"Development removed; roll {r.code} is now 'exposed'.")


def cmd_delete(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    r = lookup.find_roll(s, a.code)
    question = f"Delete roll {r.code}"
    if r.prints:
        frames = ", ".join(f"#{p.id} frame {p.frame or '?'}" for p in r.prints)
        question += f" and its {len(r.prints)} print(s) ({frames})"
    images = images_of_roll(r)
    if images:
        question += f" and {len(images)} image file(s)"
    if not confirm(question + "?", a.yes):
        return
    s.delete(r)
    roll_service.prune_unused_tags(s)
    s.commit()
    delete_unreferenced(s, images)
    ctx.note(f"Deleted roll {a.code}.")


def cmd_next_code(ctx: Ctx, a: argparse.Namespace) -> None:
    ctx.print(roll_service.suggest_code(ctx.session, a.year))


# --------------------------------------------------------------------------- recipes / card


def cmd_recipes(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    film = lookup.find_film(s, a.film)
    developer = (
        lookup.find_chemical(s, a.developer, [ChemicalKind.FILM_DEVELOPER]) if a.developer else None
    )
    devs = dev_service.past_results(
        s, film.id, developer.id if developer else None, a.dilution, limit=200
    )
    if ctx.as_json:
        print_json(ctx, [{"roll": d.roll.code, **roll_dict(d.roll)["development"]} for d in devs])
        return
    ctx.note(f"Past developments of {film.display_name} — starting points, not gospel.")
    rows = [
        (
            d.roll.code,
            d.date_developed,
            _ei(d.roll),
            _chem(d.developer, d.dilution),
            format_duration(d.dev_time_s),
            ctx.temp(d.temperature_c),
            d.agitation,
            stars(d.result_rating),
        )
        for d in devs
    ]
    headers = ("Roll", "Date", "EI", "Developer", "Time", "Temp", "Agitation", "Result")
    print_table(ctx, headers, rows, right=(4,), empty="No matching developments yet.")


def cmd_card(ctx: Ctx, a: argparse.Namespace) -> None:
    from filmlog.services.card import roll_card_html

    r = lookup.find_roll(ctx.session, a.code)
    out = Path(a.output).expanduser()
    html = roll_card_html(r, ctx.settings.temperature_unit, ctx.settings.length_unit)
    suffix = out.suffix.lower()
    if suffix in (".html", ".htm"):
        out.write_text(html, encoding="utf-8")
    elif suffix == ".pdf":
        _write_pdf(html, out)
    else:
        raise CliError("The output file must end in .pdf or .html.")
    ctx.note(f"Wrote {out}")


def _write_pdf(html: str, out: Path) -> None:
    """PDF rendering needs Qt; it runs headless (no window is opened)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication

        from filmlog.ui.file_actions import write_pdf
    except ImportError as exc:  # pragma: no cover - PySide6 is a dependency
        raise CliError(f"PDF export needs PySide6: {exc}") from exc
    _app = QApplication.instance() or QApplication([])
    write_pdf(html, out)
