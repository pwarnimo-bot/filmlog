# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""``filmlog-cli cameras`` / ``camera …``."""

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
    parse_int,
    print_fields,
    print_json,
    print_table,
)
from filmlog.db.enums import CameraStatus, CameraType, FilmFormat
from filmlog.db.models import Camera
from filmlog.services import cameras as camera_service
from filmlog.services import lookup, records
from filmlog.services.exchange import record_dict

TYPE_ALIASES = {
    "medium-format slr": CameraType.MEDIUM_FORMAT_SLR,
    "mf": CameraType.MEDIUM_FORMAT_SLR,
    "compact": CameraType.VIEWFINDER,
    "lf": CameraType.LARGE_FORMAT,
}


def register(sub: argparse._SubParsersAction[Any]) -> None:
    p = sub.add_parser("cameras", help="list cameras", description="List cameras, active first.")
    p.add_argument("search", nargs="*", default=[])
    p.set_defaults(func=cmd_list)

    cam = sub.add_parser("camera", help="show, add, edit or delete a camera")
    cs = cam.add_subparsers(dest="action", required=True, metavar="ACTION")

    p = cs.add_parser("show", help="show a camera and the rolls shot with it")
    p.add_argument("camera", help="name or #id, e.g. fm2")
    p.set_defaults(func=cmd_show)

    p = cs.add_parser("add", help="add a camera")
    _options(p, adding=True)
    p.set_defaults(func=cmd_add)

    p = cs.add_parser("edit", help="change a camera (only the given options; '-' clears)")
    p.add_argument("camera")
    _options(p, adding=False)
    p.set_defaults(func=cmd_edit)

    p = cs.add_parser("delete", help="delete a camera (its rolls are kept)")
    p.add_argument("camera")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask")
    p.set_defaults(func=cmd_delete)


def _options(p: argparse.ArgumentParser, *, adding: bool) -> None:
    p.add_argument("--make", required=adding)
    p.add_argument("--model", required=adding)
    p.add_argument("--nickname", help="e.g. 'the black FM2'")
    p.add_argument("--type", help=enum_help(CameraType))
    p.add_argument("--format", help=enum_help(FilmFormat))
    p.add_argument("--mount", help="lens mount")
    p.add_argument("--lenses", help="lenses owned for this body (comma-separated)")
    p.add_argument("--serial")
    p.add_argument("--year", help="year made")
    p.add_argument("--shutter")
    p.add_argument("--metering")
    p.add_argument("--battery")
    p.add_argument("--acquired", help="date acquired")
    p.add_argument("--price", help="price paid")
    p.add_argument("--status", help=enum_help(CameraStatus))
    p.add_argument("--notes")


def cmd_list(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    cams = camera_service.list_cameras(s, " ".join(a.search))
    counts = camera_service.roll_counts(s)
    if ctx.as_json:
        print_json(ctx, [{**record_dict(c), "rolls": counts.get(c.id, 0)} for c in cams])
        return
    rows = [
        (
            f"#{c.id}",
            c.display_name,
            f"{c.make} {c.model}",
            c.camera_type,
            c.format,
            c.lens_mount,
            c.status,
            counts.get(c.id, 0),
        )  # fmt: skip
        for c in cams
    ]
    headers = ("Id", "Name", "Make / model", "Type", "Format", "Mount", "Status", "Rolls")
    print_table(ctx, headers, rows, right=(7,), empty="No cameras yet.")


def cmd_show(ctx: Ctx, a: argparse.Namespace) -> None:
    c = lookup.find_camera(ctx.session, a.camera)
    rolls = camera_service.rolls_for(ctx.session, c.id)
    if ctx.as_json:
        print_json(ctx, {**record_dict(c), "rolls": [r.code for r in rolls]})
        return
    show_camera(ctx, c)
    if rolls:
        ctx.print()
        ctx.print(f"Rolls ({len(rolls)})")
        rows = [(r.code, r.title, r.film_stock.display_name, r.status) for r in rolls]
        print_table(ctx, ("Code", "Title", "Film", "Status"), rows)


def show_camera(ctx: Ctx, c: Camera) -> None:
    print_fields(
        ctx,
        f"Camera #{c.id} — {c.display_name}",
        [
            ("Make / model", f"{c.make} {c.model}"),
            ("Type", c.camera_type),
            ("Format", c.format),
            ("Mount", c.lens_mount),
            ("Lenses", c.lenses),
            ("Serial", c.serial_number),
            ("Year made", c.year_made),
            ("Shutter", c.shutter),
            ("Metering", c.metering),
            ("Battery", c.battery),
            ("Acquired", c.acquired_date),
            ("Price", c.acquired_price),
            ("Status", c.status),
            ("Notes", c.notes),
        ],
    )


def _apply(c: Camera, a: argparse.Namespace) -> None:
    texts = {
        "make": a.make, "model": a.model, "nickname": a.nickname, "lens_mount": a.mount,
        "lenses": a.lenses, "serial_number": a.serial, "shutter": a.shutter,
        "metering": a.metering, "battery": a.battery,
    }  # fmt: skip
    for attr, value in texts.items():
        if value is not None:
            setattr(c, attr, "" if value.strip() == "-" else value.strip())
    if a.type is not None:
        c.camera_type = parse_enum(CameraType, a.type, TYPE_ALIASES)
    if a.format is not None:
        c.format = parse_enum(FilmFormat, a.format)
    if a.year is not None:
        c.year_made = parse_int(a.year, "year")
    if a.acquired is not None:
        c.acquired_date = parse_date(a.acquired)
    if a.price is not None:
        c.acquired_price = parse_float(a.price, "price")
    if a.status is not None:
        c.status = parse_enum(CameraStatus, a.status)
    if a.notes is not None:
        c.notes = a.notes
    if not c.make or not c.model:
        raise CliError("Make and model are required.")


def _done(ctx: Ctx, c: Camera, message: str) -> None:
    if ctx.as_json:
        print_json(ctx, record_dict(c))
    else:
        ctx.note(message)
        show_camera(ctx, c)


def cmd_add(ctx: Ctx, a: argparse.Namespace) -> None:
    c = Camera(make="", model="", notes="")
    _apply(c, a)
    ctx.session.add(c)
    ctx.session.commit()
    _done(ctx, c, f"Added camera #{c.id}.")


def cmd_edit(ctx: Ctx, a: argparse.Namespace) -> None:
    c = lookup.find_camera(ctx.session, a.camera)
    _apply(c, a)
    ctx.session.commit()
    _done(ctx, c, f"Saved camera #{c.id}.")


def cmd_delete(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session
    c = lookup.find_camera(s, a.camera)
    if not confirm(records.camera_delete_question(s, c), a.yes):
        return
    records.delete_camera(s, c)
    ctx.note(f"Deleted camera “{c.display_name}”.")
