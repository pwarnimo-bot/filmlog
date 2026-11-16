# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Command-line interface: ``filmlog-cli`` (no Qt window, works over SSH)."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from filmlog import __version__

EPILOG = """\
examples:
  filmlog-cli                                        open the full-screen app
  filmlog-cli info                                   where is my data?
  filmlog-cli rolls --status exposed                 rolls waiting for the tank
  filmlog-cli roll add --film hp5 --ei 800 --camera fm2 --title "Night walk"
  filmlog-cli roll develop 2026-010 --developer id-11 --dilution 1+1 --time 13:00
  filmlog-cli recipes hp5 --developer id-11          what worked before
  filmlog-cli print add 2026-010 --frame 12 --paper "mg rc deluxe glossy" \\
              --size 18x24 --exp 00:9 --exp 5:7 --exp "5:4:burn:sky"
  filmlog-cli print duplicate 7 --exp 00:10 --exp 5:7 --final --rating 5

Names can be shortened: 'hp5', 'fm2', 'id-11'. Use #ID when a name is ambiguous.
Times: 8:30, 90 (seconds) or 1m30s.  Dates: YYYY-MM-DD, today, yesterday.
In 'edit' commands, '-' clears a field.  Add --json for machine-readable output.
"""


LIST_HINTS = {
    "film stock": "films",
    "camera": "cameras",
    "roll": "rolls",
    "print": "prints",
    "paper": "papers",
    "chemical": "chemicals",
    "film developer": "chemicals --kind film_developer",
    "paper developer": "chemicals --kind paper_developer",
    "stop bath": "chemicals --kind stop_bath",
    "fixer": "chemicals --kind fixer",
    "wetting agent": "chemicals --kind wetting_agent",
}


def build_parser() -> argparse.ArgumentParser:
    from filmlog.cli import cameras, catalogue, data, prints, rolls

    parser = argparse.ArgumentParser(
        prog="filmlog-cli",
        description="FilmLog in the terminal. Without a COMMAND it opens the full-screen app "
        "(tabs, dialogs, mouse); with a COMMAND it runs that one command, e.g. for scripts.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"FilmLog {__version__}")
    parser.add_argument("--db", metavar="FILE", help="use this database file (or set FILMLOG_DB)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of tables")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    rolls.register(sub)
    prints.register(sub)
    cameras.register(sub)
    catalogue.register(sub)
    data.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.db:
        os.environ["FILMLOG_DB"] = args.db
    if args.command is None:
        # No command: open the full-screen terminal app.
        if not sys.stdout.isatty():
            parser.error("a COMMAND is required when not running in a terminal")
        from filmlog.tui.app import run

        return run()

    from filmlog import paths
    from filmlog.cli.common import CliError, Ctx
    from filmlog.db.database import open_database
    from filmlog.services.lookup import LookupError_
    from filmlog.services.settings import Settings

    paths.ensure_dirs()
    db = open_database(paths.db_path(), paths.backups_dir())
    if db.backup_taken is not None:
        print(f"Database upgraded; backup saved to {db.backup_taken}", file=sys.stderr)
    try:
        with db.session() as session:
            ctx = Ctx(session=session, settings=Settings.load(), db=db, as_json=args.json)
            try:
                result = args.func(ctx, args)
            except (CliError, LookupError_) as exc:
                session.rollback()
                print(f"filmlog-cli: {exc}", file=sys.stderr)
                if isinstance(exc, LookupError_) and not exc.candidates:
                    hint = LIST_HINTS.get(exc.what)
                    if hint:
                        print(f"  (see: filmlog-cli {hint})", file=sys.stderr)
                return 1
            except KeyboardInterrupt:
                session.rollback()
                return 130
        return int(result or 0)
    finally:
        db.engine.dispose()
