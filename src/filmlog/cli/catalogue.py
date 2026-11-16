# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalogue lists (films, chemicals, papers, presets, manufacturers) and additions."""

from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy.exc import IntegrityError

from filmlog.cli.common import CliError, Ctx, enum_help, parse_enum, print_json, print_table
from filmlog.db.enums import (
    ChemicalForm,
    ChemicalKind,
    ContrastType,
    FilmType,
    PaperBase,
    PaperSurface,
    PaperTone,
)
from filmlog.db.models import Chemical, FilmStock, Manufacturer, Paper
from filmlog.services import catalogue, lookup
from filmlog.services.exchange import record_dict

KIND_ALIASES = {
    "film": ChemicalKind.FILM_DEVELOPER, "developer": ChemicalKind.FILM_DEVELOPER,
    "paper": ChemicalKind.PAPER_DEVELOPER, "stop": ChemicalKind.STOP_BATH,
    "wetting": ChemicalKind.WETTING_AGENT, "hypo": ChemicalKind.WASHING_AID,
    "washaid": ChemicalKind.WASHING_AID,
}  # fmt: skip


def register(sub: argparse._SubParsersAction[Any]) -> None:
    p = sub.add_parser("films", help="list film stocks")
    p.add_argument("search", nargs="*", default=[])
    p.set_defaults(func=cmd_films)

    p = sub.add_parser("chemicals", help="list chemicals")
    p.add_argument("search", nargs="*", default=[])
    p.add_argument("--kind", help=enum_help(ChemicalKind) + " (or film, paper, stop, …)")
    p.set_defaults(func=cmd_chemicals)

    p = sub.add_parser("papers", help="list papers")
    p.add_argument("search", nargs="*", default=[])
    p.set_defaults(func=cmd_papers)

    p = sub.add_parser("presets", help="list agitation presets")
    p.set_defaults(func=cmd_presets)

    p = sub.add_parser("manufacturers", help="list manufacturers")
    p.set_defaults(func=cmd_manufacturers)

    p = sub.add_parser("film", help="add a film stock to the catalogue")
    fs = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = fs.add_parser("add", help="add a film stock")
    p.add_argument("--maker", required=True, help="manufacturer (created if new)")
    p.add_argument("--name", required=True, help="e.g. 'FP4 Plus'")
    p.add_argument("--iso", required=True, type=int, help="box ISO")
    p.add_argument("--type", default="bw_negative", help=enum_help(FilmType))
    p.add_argument("--formats", default="", help="e.g. '135, 120, sheet'")
    p.add_argument("--aliases", default="")
    p.set_defaults(func=cmd_film_add)

    p = sub.add_parser("chemical", help="add a chemical to the catalogue")
    cs = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = cs.add_parser("add", help="add a chemical")
    p.add_argument("--maker", help="manufacturer (created if new; omit for home-brew)")
    p.add_argument("--name", required=True)
    p.add_argument("--kind", required=True, help=enum_help(ChemicalKind))
    p.add_argument("--dilutions", default="", help="e.g. 'stock; 1+1; 1+3'")
    p.add_argument("--form", default="liquid", help=enum_help(ChemicalForm))
    p.set_defaults(func=cmd_chemical_add)

    p = sub.add_parser("paper", help="add a paper to the catalogue")
    ps = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    p = ps.add_parser("add", help="add a paper (one entry per surface)")
    p.add_argument("--maker", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--base", default="rc", help=enum_help(PaperBase))
    p.add_argument("--surface", default="glossy", help=enum_help(PaperSurface))
    p.add_argument("--tone", default="neutral", help=enum_help(PaperTone))
    p.add_argument("--grade", help="for graded paper only")
    p.set_defaults(func=cmd_paper_add)


def _filtered(items: Any, words: list[str]) -> list[Any]:
    search = " ".join(words)
    if not search.strip():
        return list(items)
    return lookup.match_items(list(items), search, lambda x: x.display_name)


def _gone(x: Any) -> str:
    return "discontinued" if getattr(x, "discontinued", False) else ""


def cmd_films(ctx: Ctx, a: argparse.Namespace) -> None:
    films = _filtered(catalogue.film_stocks(ctx.session), a.search)
    if ctx.as_json:
        print_json(ctx, [{**record_dict(f), "display_name": f.display_name} for f in films])
        return
    rows = [(f"#{f.id}", f.display_name, f.box_iso, f.type, f.formats_available, f.aliases,
             _gone(f)) for f in films]  # fmt: skip
    print_table(ctx, ("Id", "Film", "ISO", "Type", "Formats", "Aliases", ""), rows, right=(2,))


def cmd_chemicals(ctx: Ctx, a: argparse.Namespace) -> None:
    kinds = [parse_enum(ChemicalKind, a.kind, KIND_ALIASES)] if a.kind else None
    chems = _filtered(catalogue.chemicals(ctx.session, kinds), a.search)
    if ctx.as_json:
        print_json(ctx, [{**record_dict(c), "display_name": c.display_name} for c in chems])
        return
    rows = [(f"#{c.id}", c.display_name, c.kind, c.common_dilutions, c.form, _gone(c))
            for c in chems]  # fmt: skip
    print_table(ctx, ("Id", "Chemical", "Kind", "Dilutions", "Form", ""), rows)


def cmd_papers(ctx: Ctx, a: argparse.Namespace) -> None:
    papers = _filtered(catalogue.papers(ctx.session), a.search)
    if ctx.as_json:
        print_json(ctx, [{**record_dict(p), "display_name": p.display_name} for p in papers])
        return
    rows = [(f"#{p.id}", p.display_name, p.base, p.contrast_type, p.grade, p.tone, _gone(p))
            for p in papers]  # fmt: skip
    print_table(ctx, ("Id", "Paper", "Base", "Contrast", "Grade", "Tone", ""), rows)


def cmd_presets(ctx: Ctx, a: argparse.Namespace) -> None:
    presets = catalogue.agitation_presets(ctx.session)
    if ctx.as_json:
        print_json(ctx, [record_dict(p) for p in presets])
        return
    print_table(ctx, ("Id", "Preset", "Text"), [(f"#{p.id}", p.name, p.text) for p in presets])


def cmd_manufacturers(ctx: Ctx, a: argparse.Namespace) -> None:
    ms = catalogue.manufacturers(ctx.session)
    if ctx.as_json:
        print_json(ctx, [record_dict(m) for m in ms])
        return
    print_table(ctx, ("Id", "Manufacturer", "Country"), [(f"#{m.id}", m.name, m.country)
                                                          for m in ms])  # fmt: skip


def _commit(ctx: Ctx, obj: Any) -> None:
    ctx.session.add(obj)
    try:
        ctx.session.commit()
    except IntegrityError:
        ctx.session.rollback()
        raise CliError("That entry already exists in the catalogue.") from None
    if ctx.as_json:
        print_json(ctx, record_dict(obj))
    else:
        ctx.print(f"Added #{obj.id} {obj.display_name}")


def _maker(ctx: Ctx, name: str) -> Manufacturer:
    return catalogue.find_or_create_manufacturer(ctx.session, name)


def cmd_film_add(ctx: Ctx, a: argparse.Namespace) -> None:
    m = _maker(ctx, a.maker)
    _commit(ctx, FilmStock(
        manufacturer=m, name=a.name.strip(), box_iso=a.iso, type=parse_enum(FilmType, a.type),
        formats_available=a.formats, aliases=a.aliases, notes="",
    ))  # fmt: skip


def cmd_chemical_add(ctx: Ctx, a: argparse.Namespace) -> None:
    m = _maker(ctx, a.maker) if a.maker else None
    _commit(ctx, Chemical(
        manufacturer=m, name=a.name.strip(), kind=parse_enum(ChemicalKind, a.kind, KIND_ALIASES),
        common_dilutions=a.dilutions, form=parse_enum(ChemicalForm, a.form), notes="",
    ))  # fmt: skip


def cmd_paper_add(ctx: Ctx, a: argparse.Namespace) -> None:
    m = _maker(ctx, a.maker)
    graded = a.grade is not None
    _commit(ctx, Paper(
        manufacturer=m, name=a.name.strip(), base=parse_enum(PaperBase, a.base),
        surface=parse_enum(PaperSurface, a.surface), tone=parse_enum(PaperTone, a.tone),
        contrast_type=ContrastType.GRADED if graded else ContrastType.VARIABLE,
        grade=a.grade, notes="",
    ))  # fmt: skip
