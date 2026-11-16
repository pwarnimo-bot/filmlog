# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalogue tab: films, chemicals, papers, manufacturers, agitation presets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Select, TabbedContent, TabPane

from filmlog.db.enums import (
    ChemicalForm,
    ChemicalKind,
    ContrastType,
    FilmType,
    PaperBase,
    PaperSurface,
    PaperTone,
)
from filmlog.db.models import AgitationPreset, Chemical, FilmStock, Manufacturer, Paper
from filmlog.services import catalogue
from filmlog.tui.forms import ConfirmScreen, Field, FormScreen
from filmlog.tui.listpane import Col, ListPane, select_value
from filmlog.tui.options import enum_options, label


def maker_field(session: Any, required: bool = True) -> Field:
    names = [m.name for m in catalogue.manufacturers(session)]
    return Field(
        "maker",
        "Manufacturer",
        required=required,
        suggestions=names,
        placeholder="type a name; new ones are created",
    )


class CataloguePane(ListPane):
    """List + form for one catalogue table."""

    title = ""
    has_discontinued = True

    def fields(self) -> list[Field]:
        raise NotImplementedError

    def values(self, obj: Any) -> dict[str, Any]:
        return {f.key: getattr(obj, f.key, None) for f in self.fields() if f.kind != "section"}

    def blank(self) -> Any:
        raise NotImplementedError

    def apply(self, obj: Any, v: dict[str, Any]) -> None:
        for k, val in v.items():
            if k == "maker":
                obj.manufacturer = (
                    catalogue.find_or_create_manufacturer(self.session, val) if val else None
                )
            else:
                setattr(obj, k, val)

    def item_dimmed(self, obj: Any) -> bool:
        return bool(getattr(obj, "discontinued", False))

    def _form(self, obj: Any) -> None:
        is_new = obj.id is None
        values = self.values(obj)
        if hasattr(obj, "manufacturer"):
            values["maker"] = obj.manufacturer.name if obj.manufacturer else ""
        note = ""
        if not is_new:
            n = catalogue.usage_count(self.session, obj)
            if n:
                note = f"Used by {n} record(s) — changes apply to all of them."

        def done(result: dict[str, Any] | None) -> None:
            if result is None:
                return
            s = self.session
            with s.no_autoflush:
                self.apply(obj, result)
            s.add(obj)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                self.app.notify("An entry with these values already exists.", severity="error")
                return
            self.tui.data_changed(select=obj)
            self.app.notify(f"Saved {obj.display_name}.")

        heading = (
            f"New {self.title}" if is_new else f"{self.title.capitalize()} — {obj.display_name}"
        )
        self.app.push_screen(FormScreen(heading, self.fields(), values, note=note), done)

    def new_item(self) -> None:
        self._form(self.blank())

    def open_item(self, obj: Any) -> None:
        self._form(obj)

    def delete_item(self, obj: Any) -> None:
        s = self.session
        if catalogue.can_delete(s, obj):

            def answer(ok: bool | None) -> None:
                if ok:
                    s.delete(obj)
                    s.commit()
                    self.tui.data_changed()

            self.app.push_screen(
                ConfirmScreen(f"Delete “{obj.display_name}”? This cannot be undone.", yes="Delete"),
                answer,
            )
            return
        n = catalogue.usage_count(s, obj)
        if not self.has_discontinued or getattr(obj, "is_builtin", False):
            why = (
                "is built in" if getattr(obj, "is_builtin", False) else f"is used by {n} record(s)"
            )
            self.app.notify(
                f"“{obj.display_name}” {why} and cannot be deleted.", severity="warning"
            )
            return

        def mark(ok: bool | None) -> None:
            if ok:
                obj.discontinued = True
                s.commit()
                self.tui.data_changed(select=obj)

        self.app.push_screen(
            ConfirmScreen(
                f"“{obj.display_name}” is used by {n} record(s) and cannot be deleted.\n\n"
                "Mark it as discontinued instead? It stays on existing records but is hidden "
                "from new ones.",
                yes="Mark discontinued",
                no="Cancel",
            ),
            mark,
        )


def _gone(obj: Any) -> str:
    return "discontinued" if obj.discontinued else ""


class FilmsPane(CataloguePane):
    title = "film stock"
    new_label = "New film"
    columns = [
        Col("Film", lambda f: f.display_name, width=34),
        Col("ISO", lambda f: f.box_iso, sort=lambda f: f.box_iso, right=True, width=5),
        Col("Type", lambda f: label(f.type), width=22),
        Col("Formats", lambda f: f.formats_available, width=16),
        Col("Aliases", lambda f: f.aliases, width=20),
        Col("", _gone, width=12),
    ]

    def fetch(self) -> Sequence[Any]:
        return catalogue.film_stocks(self.session)

    def fields(self) -> list[Field]:
        return film_fields(self.session)

    def blank(self) -> Any:
        return new_film()


def film_fields(session: Any) -> list[Field]:
    return [
        maker_field(session),
        Field("name", "Name", required=True, placeholder="e.g. FP4 Plus"),
        Field("box_iso", "Box ISO", "int", required=True),
        Field("type", "Type", "select", enum_options(FilmType), allow_blank=False),
        Field("formats_available", "Formats", placeholder="e.g. 135, 120, sheet"),
        Field("aliases", "Aliases", placeholder="other names, e.g. T-Max 400"),
        Field("discontinued", "Discontinued", "bool"),
        Field("notes", "Notes", "area"),
    ]


def new_film() -> FilmStock:
    return FilmStock(
        name="",
        box_iso=100,
        type=FilmType.BW_NEGATIVE,
        formats_available="",
        aliases="",
        discontinued=False,
        notes="",
    )


def save_new_film(pane_app: Any, on_saved: Callable[[FilmStock], None]) -> None:
    """Open the film form; call ``on_saved`` with the created film."""
    session = pane_app.session
    film = new_film()

    def done(result: dict[str, Any] | None) -> None:
        if result is None:
            return
        maker = result.pop("maker")
        film.manufacturer = catalogue.find_or_create_manufacturer(session, maker)
        for k, v in result.items():
            setattr(film, k, v)
        session.add(film)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            pane_app.notify("That film stock already exists.", severity="error")
            return
        pane_app.data_changed()
        on_saved(film)

    pane_app.push_screen(FormScreen("New film stock", film_fields(session), {}), done)


class ChemicalsPane(CataloguePane):
    title = "chemical"
    new_label = "New chemical"
    columns = [
        Col("Chemical", lambda c: c.display_name, width=34),
        Col("Kind", lambda c: label(c.kind), width=24),
        Col("Dilutions", lambda c: c.common_dilutions, width=22),
        Col("Form", lambda c: label(c.form), width=8),
        Col("", _gone, width=12),
    ]

    def filter_widgets(self) -> list[Select[Any]]:
        return [Select(enum_options(ChemicalKind), prompt="Any kind", id="kind", compact=True)]

    def fetch(self) -> Sequence[Any]:
        kinds = None
        try:
            kind = select_value(self.query_one("#kind", Select))
            kinds = [kind] if kind else None
        except Exception:  # not mounted yet
            pass
        return catalogue.chemicals(self.session, kinds)

    def fields(self) -> list[Field]:
        return [
            maker_field(self.session, required=False),
            Field("name", "Name", required=True),
            Field("kind", "Kind", "select", enum_options(ChemicalKind), allow_blank=False),
            Field("common_dilutions", "Dilutions", placeholder="e.g. stock; 1+1; 1+3"),
            Field("form", "Form", "select", enum_options(ChemicalForm), allow_blank=False),
            Field("discontinued", "Discontinued", "bool"),
            Field("notes", "Notes", "area"),
        ]

    def blank(self) -> Any:
        return Chemical(
            name="",
            kind=ChemicalKind.FILM_DEVELOPER,
            common_dilutions="",
            form=ChemicalForm.LIQUID,
            discontinued=False,
            notes="",
        )


class PapersPane(CataloguePane):
    title = "paper"
    new_label = "New paper"
    columns = [
        Col("Paper", lambda p: p.display_name, width=40),
        Col("Base", lambda p: label(p.base), width=5),
        Col("Contrast", lambda p: label(p.contrast_type), width=18),
        Col("Grade", lambda p: p.grade, width=6),
        Col("Tone", lambda p: label(p.tone), width=8),
        Col("", _gone, width=12),
    ]

    def fetch(self) -> Sequence[Any]:
        return catalogue.papers(self.session)

    def fields(self) -> list[Field]:
        return [
            maker_field(self.session),
            Field("name", "Name", required=True),
            Field("base", "Base", "select", enum_options(PaperBase), allow_blank=False),
            Field(
                "contrast_type", "Contrast", "select", enum_options(ContrastType), allow_blank=False
            ),
            Field("grade", "Grade", placeholder="graded paper only"),
            Field("surface", "Surface", "select", enum_options(PaperSurface), allow_blank=False),
            Field("tone", "Tone", "select", enum_options(PaperTone), allow_blank=False),
            Field("discontinued", "Discontinued", "bool"),
            Field("notes", "Notes", "area"),
        ]

    def apply(self, obj: Any, v: dict[str, Any]) -> None:
        if v.get("contrast_type") != ContrastType.GRADED:
            v["grade"] = None
        super().apply(obj, v)

    def blank(self) -> Any:
        return Paper(
            name="",
            base=PaperBase.RC,
            contrast_type=ContrastType.VARIABLE,
            surface=PaperSurface.GLOSSY,
            tone=PaperTone.NEUTRAL,
            discontinued=False,
            notes="",
        )


class ManufacturersPane(CataloguePane):
    title = "manufacturer"
    new_label = "New"
    has_discontinued = False
    columns = [
        Col("Manufacturer", lambda m: m.name, width=30),
        Col("Country", lambda m: m.country, width=20),
    ]

    def fetch(self) -> Sequence[Any]:
        return catalogue.manufacturers(self.session)

    def item_dimmed(self, obj: Any) -> bool:
        return False

    def fields(self) -> list[Field]:
        return [
            Field("name", "Name", required=True),
            Field("country", "Country"),
            Field("notes", "Notes", "area"),
        ]

    def blank(self) -> Any:
        return Manufacturer(name="", notes="")


class PresetsPane(CataloguePane):
    title = "agitation preset"
    new_label = "New preset"
    has_discontinued = False
    columns = [
        Col("Preset", lambda p: p.name, width=26),
        Col("Text", lambda p: p.text, width=70),
    ]

    def fetch(self) -> Sequence[Any]:
        return catalogue.agitation_presets(self.session)

    def item_dimmed(self, obj: Any) -> bool:
        return False

    def fields(self) -> list[Field]:
        return [
            Field("name", "Name", required=True),
            Field("text", "Text", "area", required=True),
            Field("sort_order", "Sort order", "int"),
        ]

    def apply(self, obj: Any, v: dict[str, Any]) -> None:
        v["sort_order"] = v.get("sort_order") or 0
        super().apply(obj, v)

    def blank(self) -> Any:
        return AgitationPreset(name="", text="", sort_order=0, notes="")


class CatalogueView(Vertical):
    DEFAULT_CSS = "CatalogueView { height: 1fr; }"

    def compose(self) -> ComposeResult:
        with TabbedContent(id="catalogue-tabs"):
            with TabPane("Films", id="cat-films"):
                yield FilmsPane()
            with TabPane("Chemicals", id="cat-chemicals"):
                yield ChemicalsPane()
            with TabPane("Papers", id="cat-papers"):
                yield PapersPane()
            with TabPane("Manufacturers", id="cat-manufacturers"):
                yield ManufacturersPane()
            with TabPane("Agitation presets", id="cat-presets"):
                yield PresetsPane()

    def active_pane(self) -> ListPane | None:
        tabs = self.query_one("#catalogue-tabs", TabbedContent)
        pane = tabs.active_pane
        return pane.query_one(ListPane) if pane is not None else None
