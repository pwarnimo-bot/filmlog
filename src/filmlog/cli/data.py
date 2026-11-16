# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""``info``, ``stats``, ``export``, ``import``, ``backup``, ``demo``."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from filmlog import paths
from filmlog.cli.common import CliError, Ctx, print_fields, print_json, print_table
from filmlog.db.models import Camera, Print, Roll
from filmlog.services import demo, stats
from filmlog.services.backup import backup_database, list_backups, timestamped_backup
from filmlog.services.exchange import (
    ConflictChoice,
    ExchangeError,
    export_csv_zip,
    export_json,
    import_json,
)
from filmlog.services.pushpull import badge_text


def register(sub: argparse._SubParsersAction[Any]) -> None:
    p = sub.add_parser("info", help="where the data lives, and how much there is")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("path", help="print the database file path")
    p.set_defaults(func=cmd_path)

    p = sub.add_parser("stats", help="rolls per year, most used films/developers/cameras")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("export", help="export everything as JSON or a zip of CSV files")
    p.add_argument("format", choices=("json", "csv"))
    p.add_argument("output", help="file to write (.json or .zip)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser(
        "import",
        help="import a FilmLog JSON export (merged by roll code)",
        description="Import a JSON export. Rolls whose code already exists are skipped unless "
        "--replace is given. A backup is taken first.",
    )
    p.add_argument("input")
    p.add_argument("--replace", action="store_true", help="replace rolls with the same code")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("backup", help="back up the database now")
    p.add_argument("output", nargs="?", help="file to write (default: the backups folder)")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("demo", help="load or remove the demo cameras, rolls and prints")
    p.add_argument("action", choices=("load", "remove"))
    p.set_defaults(func=cmd_demo)


def cmd_path(ctx: Ctx, a: argparse.Namespace) -> None:
    ctx.print(str(ctx.db.path))


def cmd_info(ctx: Ctx, a: argparse.Namespace) -> None:
    s = ctx.session

    def count(model: Any) -> int:
        return int(s.scalar(select(func.count()).select_from(model)) or 0)

    db_file = ctx.db.path
    backups = list_backups(paths.backups_dir())
    info = {
        "database": str(db_file),
        "database_size_kb": round(db_file.stat().st_size / 1024) if db_file.exists() else 0,
        "images": str(paths.images_dir()),
        "backups": str(paths.backups_dir()),
        "backup_count": len(backups),
        "latest_backup": backups[-1].name if backups else None,
        "settings": str(paths.config_file()),
        "rolls": count(Roll),
        "prints": count(Print),
        "cameras": count(Camera),
    }
    if ctx.as_json:
        print_json(ctx, info)
        return
    override = " (from $FILMLOG_DB)" if os.environ.get("FILMLOG_DB") else ""
    print_fields(
        ctx,
        "FilmLog data",
        [
            ("Database", f"{info['database']}{override}"),
            ("Size", f"{info['database_size_kb']} KiB"),
            ("Images", info["images"]),
            ("Backups", f"{info['backups']} ({len(backups)} kept)"),
            ("Settings", info["settings"]),
            (
                "Contents",
                f"{info['rolls']} rolls, {info['prints']} prints, {info['cameras']} cameras",
            ),  # fmt: skip
        ],
    )


def cmd_stats(ctx: Ctx, a: argparse.Namespace) -> None:
    st = stats.compute(ctx.session)
    if ctx.as_json:
        print_json(ctx, st.__dict__)
        return
    ctx.print(f"{st.total_rolls} rolls, {st.total_prints} prints ({st.final_prints} final)")
    sections: list[tuple[str, list[tuple[str, int]]]] = [
        ("Rolls per year", st.rolls_per_year),
        ("Films", st.top_films),
        ("Developers", st.top_developers),
        ("Cameras", st.top_cameras),
        ("Push / pull", [(badge_text(k), v) for k, v in st.push_pull]),
    ]
    for title, items in sections:
        if not items:
            continue
        ctx.print()
        peak = max(v for _, v in items) or 1
        rows = [(k, v, "█" * max(1, round(20 * v / peak))) for k, v in items]
        print_table(ctx, (title, "Rolls", ""), rows, right=(1,))


def cmd_export(ctx: Ctx, a: argparse.Namespace) -> None:
    out = Path(a.output).expanduser()
    if a.format == "json":
        export_json(ctx.session, out)
    else:
        export_csv_zip(ctx.session, out)
    ctx.note(f"Exported to {out}")


def cmd_import(ctx: Ctx, a: argparse.Namespace) -> None:
    src = Path(a.input).expanduser()
    if not src.is_file():
        raise CliError(f"No such file: {src}")
    backup = timestamped_backup(ctx.db.path, paths.backups_dir())
    ctx.note(f"Backup saved to {backup}")
    choice: ConflictChoice = "replace" if a.replace else "skip"
    try:
        res = import_json(ctx.session, src, lambda _code: choice)
        ctx.session.commit()
    except ExchangeError as exc:
        ctx.session.rollback()
        raise CliError(str(exc)) from None
    if ctx.as_json:
        print_json(ctx, res.__dict__)
        return
    ctx.print(
        f"Imported: {len(res.rolls_created)} new roll(s), {len(res.rolls_replaced)} replaced, "
        f"{len(res.rolls_skipped)} skipped (code already used); {res.cameras_created} camera(s) "
        f"and {res.catalogue_created} catalogue entries added."
    )
    if res.rolls_skipped and not a.replace:
        ctx.print("Skipped: " + ", ".join(res.rolls_skipped) + "  (use --replace to overwrite)")
    for w in res.warnings:
        ctx.note(f"warning: {w}")


def cmd_backup(ctx: Ctx, a: argparse.Namespace) -> None:
    ctx.session.commit()
    if a.output:
        out = Path(a.output).expanduser()
        if out.exists() and out.resolve() == ctx.db.path.resolve():
            raise CliError("Choose a file other than the database itself.")
        backup_database(ctx.db.path, out)
    else:
        out = timestamped_backup(ctx.db.path, paths.backups_dir())
    ctx.print(f"Backup saved to {out}")


def cmd_demo(ctx: Ctx, a: argparse.Namespace) -> None:
    if a.action == "load":
        res = demo.load_demo(ctx.session)
        ctx.print(f"Loaded {len(res.rolls_created)} demo roll(s) and {res.cameras_created} "
                  "camera(s). Remove them again with: filmlog-cli demo remove")  # fmt: skip
    else:
        r = demo.remove_demo(ctx.session)
        ctx.print(f"Removed {r.rolls} demo roll(s), {r.prints} print(s), {r.cameras} camera(s).")
        if r.cameras_kept:
            ctx.print(f"Kept {r.cameras_kept} demo camera(s) that your own rolls use.")
