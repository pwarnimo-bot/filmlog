# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""FilmLog in the terminal: a full-screen app with tabs and dialogs (Textual)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from filmlog import __version__, paths
from filmlog.db.database import Database
from filmlog.services import demo, stats
from filmlog.services.backup import backup_database, timestamped_backup
from filmlog.services.exchange import ExchangeError, export_csv_zip, export_json, import_json
from filmlog.services.pushpull import badge_text
from filmlog.services.settings import Settings
from filmlog.tui.cameras import CamerasPane
from filmlog.tui.catalogue import CatalogueView
from filmlog.tui.forms import ConfirmScreen, Field, FormScreen, PromptScreen
from filmlog.tui.listpane import ListPane
from filmlog.tui.prints import PrintsPane
from filmlog.tui.rolls import RollScreen, RollsPane

DARKROOM = Theme(
    name="darkroom",
    primary="#b00000",
    secondary="#800000",
    accent="#c00000",
    warning="#c00000",
    error="#ff2020",
    success="#900000",
    foreground="#a00000",
    background="#000000",
    surface="#0a0000",
    panel="#140000",
    dark=True,
)

# Settings.theme (shared with the window app) → Textual theme.
THEME_MAP = {
    "system": "ansi-dark",  # the terminal's own colour palette
    "light": "textual-light",
    "dark": "textual-dark",
    "darkroom": "darkroom",
}

TABS = ("rolls", "prints", "cameras", "catalogue", "statistics")


class StatisticsView(VerticalScroll):
    DEFAULT_CSS = "StatisticsView { padding: 1 2; }"

    def compose(self) -> ComposeResult:
        yield Static("", id="stats")

    def reload(self) -> None:
        app: FilmLogTUI = self.app  # type: ignore[assignment]
        st = stats.compute(app.session)
        parts: list[Any] = [
            Text(
                f"{st.total_rolls} rolls · {st.total_prints} prints ({st.final_prints} final)\n",
                style="bold",
            ),
        ]
        sections = [
            ("Rolls per year", st.rolls_per_year),
            ("Most used films", st.top_films),
            ("Most used developers", st.top_developers),
            ("Most used cameras", st.top_cameras),
            ("Push / pull", [(badge_text(k), v) for k, v in st.push_pull]),
        ]
        for title, items in sections:
            if not items:
                continue
            t = Table(
                title=title,
                title_justify="left",
                title_style="bold",
                box=None,
                show_header=False,
                padding=(0, 1),
            )
            t.add_column(no_wrap=True)
            t.add_column(justify="right")
            t.add_column(style="bold")
            peak = max(v for _, v in items) or 1
            for k, v in items:
                t.add_row(str(k), str(v), "█" * max(1, round(30 * v / peak)))
            parts += [t, Text("")]
        if not st.total_rolls:
            parts.append(Text("No rolls yet.", style="dim"))
        self.query_one("#stats", Static).update(Group(*parts))


class MainScreen(Screen[None]):
    BINDINGS = [
        Binding("1", "tab('rolls')", "Rolls", show=False),
        Binding("2", "tab('prints')", "Prints", show=False),
        Binding("3", "tab('cameras')", "Cameras", show=False),
        Binding("4", "tab('catalogue')", "Catalogue", show=False),
        Binding("5", "tab('statistics')", "Statistics", show=False),
        Binding("ctrl+f", "search", "Search"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="main-tabs"):
            with TabPane("Rolls [1]", id="rolls"):
                yield RollsPane()
            with TabPane("Prints [2]", id="prints"):
                yield PrintsPane()
            with TabPane("Cameras [3]", id="cameras"):
                yield CamerasPane()
            with TabPane("Catalogue [4]", id="catalogue"):
                yield CatalogueView()
            with TabPane("Statistics [5]", id="statistics"):
                yield StatisticsView()
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_table)

    def _focus_table(self) -> None:
        pane = self.active_list()
        if pane is not None:
            pane.table.focus()

    def action_tab(self, tab: str) -> None:
        self.query_one("#main-tabs", TabbedContent).active = tab
        self.call_after_refresh(self._focus_table)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "statistics":
            self.query_one(StatisticsView).reload()

    def active_list(self) -> ListPane | None:
        tabs = self.query_one("#main-tabs", TabbedContent)
        pane = tabs.active_pane
        if pane is None:
            return None
        if pane.id == "catalogue":
            return self.query_one(CatalogueView).active_pane()
        found = pane.query(ListPane)
        return found.first() if found else None

    def action_search(self) -> None:
        pane = self.active_list()
        if pane is not None:
            pane.focus_search()


class FilmLogTUI(App[None]):
    TITLE = "FilmLog"
    SUB_TITLE = "darkroom film & print manager"
    BINDINGS = [
        Binding("ctrl+n", "new", "New"),
        Binding("f2", "settings", "Settings"),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]
    CSS = """
    TabbedContent ContentSwitcher { height: 1fr; }
    TabPane { padding: 1 1 0 1; }
    .title { text-style: bold; color: $primary; padding: 0 0 1 0; }
    """

    def __init__(self, db: Database, settings: Settings) -> None:
        super().__init__()
        self.db = db
        self.settings = settings
        self.session = db.session()

    def on_mount(self) -> None:
        self.register_theme(DARKROOM)
        self.apply_theme()
        self.push_screen(MainScreen())
        if self.db.backup_taken is not None:
            self.notify(f"Database upgraded; backup saved to {self.db.backup_taken}")

    def on_unmount(self) -> None:
        self.session.close()

    def apply_theme(self) -> None:
        name = THEME_MAP.get(self.settings.theme, "textual-dark")
        self.theme = name if name in self.available_themes else "textual-dark"

    # -- shared --------------------------------------------------------------------

    @property
    def main(self) -> MainScreen | None:
        for s in self.screen_stack:
            if isinstance(s, MainScreen):
                return s
        return None

    def data_changed(self, select: Any = None) -> None:
        """Reload every list (cheap for a personal catalogue)."""
        main = self.main
        if main is None:
            return
        for pane in main.query(ListPane):
            if hasattr(pane, "refresh_filter_options"):
                pane.refresh_filter_options()
            pane.reload(select=select)
        main.query_one(StatisticsView).reload()

    def action_new(self) -> None:
        screen = self.screen
        if isinstance(screen, MainScreen):
            pane = screen.active_list()
            if pane is not None:
                pane.new_item()
        elif isinstance(screen, RollScreen):
            screen.action_add_print()

    # -- command palette (ctrl+p) ---------------------------------------------------

    def get_system_commands(self, screen: Screen[Any]) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Settings", "Theme (incl. Darkroom), °C/°F, cm/in", self.action_settings
        )
        yield SystemCommand(
            "Where is my data?", "Database, images and backup locations", self.action_show_paths
        )
        yield SystemCommand(
            "Export to JSON", "Full nested export of everything", lambda: self._export("json")
        )
        yield SystemCommand("Export to CSV (zip)", "One CSV per table", lambda: self._export("csv"))
        yield SystemCommand(
            "Import JSON", "Merge a FilmLog export (by roll code)", self.action_import
        )
        yield SystemCommand(
            "Back up database now", "Save a copy of the database", self.action_backup
        )
        if demo.has_demo_data(self.session):
            yield SystemCommand(
                "Remove demo data",
                "Delete the demo cameras, rolls and prints",
                self.action_remove_demo,
            )
        yield SystemCommand(
            "Load demo data", "Example cameras, rolls and prints", self.action_load_demo
        )
        yield SystemCommand("About FilmLog", "Version and licence", self.action_about)

    def action_settings(self) -> None:
        s = self.settings
        fields = [
            Field(
                "theme",
                "Theme",
                "select",
                [
                    ("Terminal colours", "system"),
                    ("Light", "light"),
                    ("Dark", "dark"),
                    ("Darkroom (dim red, for the safelight)", "darkroom"),
                ],
                allow_blank=False,
            ),
            Field(
                "temperature_unit",
                "Temperature",
                "select",
                [("°C", "C"), ("°F", "F")],
                allow_blank=False,
            ),
            Field(
                "length_unit",
                "Length",
                "select",
                [("cm", "cm"), ("inches", "in")],
                allow_blank=False,
            ),
        ]

        def done(v: dict[str, Any] | None) -> None:
            if v is None:
                return
            s.theme = v["theme"]
            s.temperature_unit = v["temperature_unit"]
            s.length_unit = v["length_unit"]
            s.save()
            self.apply_theme()
            self.data_changed()
            self.notify("Settings saved (shared with the window app).")

        self.push_screen(
            FormScreen(
                "Settings",
                fields,
                {
                    "theme": s.theme,
                    "temperature_unit": s.temperature_unit,
                    "length_unit": s.length_unit,
                },
            ),
            done,
        )

    def action_show_paths(self) -> None:
        msg = (
            f"Database: {self.db.path}\nImages:   {paths.images_dir()}\n"
            f"Backups:  {paths.backups_dir()}\nSettings: {paths.config_file()}"
        )
        self.push_screen(ConfirmScreen(msg, yes="OK", no="Close"))

    def action_about(self) -> None:
        self.push_screen(
            ConfirmScreen(
                f"FilmLog {__version__} — darkroom film & print manager.\n"
                "© 2026 Pol Warnimont · GPL-3.0-or-later.\n\n"
                "Keys: 1–5 tabs · Enter/click opens · ctrl+n new · ctrl+f search · "
                "Delete deletes · ctrl+s saves a dialog · Esc goes back · ctrl+p commands.",
                yes="OK",
                no="Close",
            )
        )

    def _export(self, kind: str) -> None:
        stamp = dt.date.today().isoformat()
        ext = "json" if kind == "json" else "zip"
        default = str(Path.home() / f"filmlog-export-{stamp}.{ext}")

        def write(path: str | None) -> None:
            if not path:
                return
            out = Path(path).expanduser()
            try:
                if kind == "json":
                    export_json(self.session, out)
                else:
                    export_csv_zip(self.session, out)
            except OSError as exc:
                self.notify(f"Export failed: {exc}", severity="error")
                return
            self.notify(f"Exported to {out}")

        self.push_screen(PromptScreen(f"Export {kind.upper()} to:", default, ok="Export"), write)

    def action_import(self) -> None:
        def ask_mode(path: str | None) -> None:
            if not path:
                return
            src = Path(path).expanduser()
            if not src.is_file():
                self.notify(f"No such file: {src}", severity="error")
                return

            def run(replace: bool | None) -> None:
                backup = timestamped_backup(self.db.path, paths.backups_dir())
                try:
                    choice: Any = "replace" if replace else "skip"
                    res = import_json(self.session, src, lambda _c: choice)
                    self.session.commit()
                except ExchangeError as exc:
                    self.session.rollback()
                    self.notify(str(exc), severity="error")
                    return
                self.data_changed()
                self.notify(
                    f"Imported {len(res.rolls_created)} new roll(s), {len(res.rolls_replaced)} "
                    f"replaced, {len(res.rolls_skipped)} skipped. Backup: {backup.name}",
                    timeout=10,
                )

            self.push_screen(
                ConfirmScreen(
                    "When a roll code already exists: replace your roll with the imported one, "
                    "or keep yours and skip it?",
                    yes="Replace",
                    no="Skip",
                ),
                run,
            )

        self.push_screen(PromptScreen("Import a FilmLog JSON export:", "", ok="Next"), ask_mode)

    def action_backup(self) -> None:
        default = str(paths.backups_dir() / f"filmlog-manual-{dt.datetime.now():%Y%m%d-%H%M}.db")

        def write(path: str | None) -> None:
            if not path:
                return
            out = Path(path).expanduser()
            if out.exists() and out.resolve() == self.db.path.resolve():
                self.notify("Choose a file other than the database itself.", severity="error")
                return
            self.session.commit()
            backup_database(self.db.path, out)
            self.notify(f"Backup saved to {out}")

        self.push_screen(PromptScreen("Back up the database to:", default, ok="Back up"), write)

    def action_load_demo(self) -> None:
        res = demo.load_demo(self.session)
        self.data_changed()
        self.notify(
            f"Loaded {len(res.rolls_created)} demo roll(s) and {res.cameras_created} "
            "camera(s). Remove them via ctrl+p → Remove demo data."
        )

    def action_remove_demo(self) -> None:
        def answer(ok: bool | None) -> None:
            if ok:
                r = demo.remove_demo(self.session)
                self.data_changed()
                self.notify(
                    f"Removed {r.rolls} demo roll(s), {r.prints} print(s), {r.cameras} camera(s)."
                )

        self.push_screen(
            ConfirmScreen("Delete all demo cameras, rolls and prints?", yes="Remove"), answer
        )


def run() -> int:
    from filmlog.db.database import open_database

    paths.ensure_dirs()
    db = open_database(paths.db_path(), paths.backups_dir())
    try:
        FilmLogTUI(db, Settings.load()).run()
    finally:
        db.engine.dispose()
    return 0
