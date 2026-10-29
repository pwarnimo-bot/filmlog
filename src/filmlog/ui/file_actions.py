"""File / Help menu actions: export, import, backup, darkroom card, demo data."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from filmlog import paths
from filmlog.db.models import Roll
from filmlog.services import demo
from filmlog.services.backup import backup_database, timestamped_backup
from filmlog.services.card import roll_card_html
from filmlog.services.exchange import (
    ConflictChoice,
    ExchangeError,
    export_csv_zip,
    export_json,
    import_json,
)
from filmlog.ui.context import AppContext


def _stamp() -> str:
    return dt.date.today().isoformat()


def _save_path(parent: QWidget, title: str, name: str, flt: str) -> Path | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, str(Path.home() / name), flt)
    return Path(path) if path else None


def export_csv(parent: QWidget, ctx: AppContext) -> None:
    path = _save_path(parent, parent.tr("Export to CSV"), f"filmlog-{_stamp()}-csv.zip",
                      parent.tr("Zip archive (*.zip)"))  # fmt: skip
    if path is None:
        return
    names = export_csv_zip(ctx.session, path)
    QMessageBox.information(
        parent,
        parent.tr("Export"),
        parent.tr("Exported {0} CSV files to\n{1}").format(len(names), path),
    )


def export_full_json(parent: QWidget, ctx: AppContext) -> None:
    path = _save_path(parent, parent.tr("Export to JSON"), f"filmlog-{_stamp()}.json",
                      parent.tr("JSON (*.json)"))  # fmt: skip
    if path is None:
        return
    export_json(ctx.session, path)
    QMessageBox.information(
        parent,
        parent.tr("Export"),
        parent.tr(
            "Exported everything to\n{0}\n\nImage files are not included; back up the "
            "images folder ({1}) separately."
        ).format(path, paths.images_dir()),
    )


def import_full_json(parent: QWidget, ctx: AppContext) -> bool:
    path, _ = QFileDialog.getOpenFileName(
        parent, parent.tr("Import JSON"), str(Path.home()), parent.tr("JSON (*.json)")
    )
    if not path:
        return False
    remembered: list[ConflictChoice] = []

    def ask(code: str) -> ConflictChoice:
        if remembered:
            return remembered[0]
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(parent.tr("Roll already exists"))
        box.setText(parent.tr("Roll {0} already exists in your database.").format(code))
        box.setInformativeText(
            parent.tr("Keep your version (skip) or replace it with the imported one?")
        )
        skip = box.addButton(parent.tr("Skip"), QMessageBox.ButtonRole.RejectRole)
        replace = box.addButton(parent.tr("Replace"), QMessageBox.ButtonRole.DestructiveRole)
        skip_all = box.addButton(parent.tr("Skip all"), QMessageBox.ButtonRole.RejectRole)
        replace_all = box.addButton(
            parent.tr("Replace all"), QMessageBox.ButtonRole.DestructiveRole
        )
        box.setDefaultButton(skip)
        box.exec()
        clicked = box.clickedButton()
        if clicked is skip_all:
            remembered.append("skip")
        elif clicked is replace_all:
            remembered.append("replace")
        return "replace" if clicked in (replace, replace_all) else "skip"

    s = ctx.session
    try:
        s.commit()
        timestamped_backup(ctx.db.path, paths.backups_dir())  # safety net before merging
        res = import_json(s, Path(path), ask)
        s.commit()
    except ExchangeError as exc:
        s.rollback()
        QMessageBox.warning(parent, parent.tr("Import"), str(exc))
        return False
    except Exception as exc:  # noqa: BLE001 - report anything unexpected, keep data intact
        s.rollback()
        QMessageBox.critical(parent, parent.tr("Import failed"), str(exc))
        return False
    msg = parent.tr("Created {0} roll(s), replaced {1}, skipped {2}. New cameras: {3}.").format(
        len(res.rolls_created), len(res.rolls_replaced), len(res.rolls_skipped),
        res.cameras_created,
    )  # fmt: skip
    if res.warnings:
        msg += "\n\n" + "\n".join(res.warnings[:20])
    QMessageBox.information(parent, parent.tr("Import"), msg)
    return True


def backup_now(parent: QWidget, ctx: AppContext) -> None:
    path = _save_path(parent, parent.tr("Back up database"), f"filmlog-backup-{_stamp()}.db",
                      parent.tr("SQLite database (*.db)"))  # fmt: skip
    if path is None:
        return
    if path.resolve() == ctx.db.path.resolve():
        QMessageBox.warning(parent, parent.tr("Backup"), parent.tr("Choose a different file."))
        return
    ctx.session.commit()
    backup_database(ctx.db.path, path)
    QMessageBox.information(parent, parent.tr("Backup"), parent.tr("Saved to\n{0}").format(path))


def render_card_pdf(roll: Roll, ctx: AppContext, path: Path) -> None:
    html = roll_card_html(roll, ctx.settings.temperature_unit, ctx.settings.length_unit)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15),
            QPageLayout.Unit.Millimeter,
        )  # fmt: skip
    )
    doc = QTextDocument()
    doc.setHtml(html)
    doc.setPageSize(QSizeF(printer.pageRect(QPrinter.Unit.Point).size()))
    doc.print_(printer)


def export_card(parent: QWidget, ctx: AppContext, roll: Roll | None) -> None:
    if roll is None or roll.id is None:
        QMessageBox.information(
            parent, parent.tr("Darkroom card"), parent.tr("Select a roll in the Rolls view first.")
        )
        return
    path = _save_path(parent, parent.tr("Export darkroom card"), f"darkroom-card-{roll.code}.pdf",
                      parent.tr("PDF (*.pdf)"))  # fmt: skip
    if path is None:
        return
    render_card_pdf(roll, ctx, path)


def load_demo(parent: QWidget, ctx: AppContext) -> bool:
    res = demo.load_demo(ctx.session)
    msg = parent.tr("Added {0} demo roll(s) and {1} camera(s).").format(
        len(res.rolls_created), res.cameras_created
    )
    if res.rolls_skipped:
        msg += "\n" + parent.tr("Skipped (code already used): {0}").format(
            ", ".join(res.rolls_skipped)
        )
    msg += "\n\n" + parent.tr(
        "Demo development times are common published starting points, not recommendations."
    )
    QMessageBox.information(parent, parent.tr("Demo data"), msg)
    return True


def remove_demo(parent: QWidget, ctx: AppContext) -> bool:
    if not demo.has_demo_data(ctx.session):
        QMessageBox.information(parent, parent.tr("Demo data"), parent.tr("No demo data found."))
        return False
    btn = QMessageBox.question(
        parent,
        parent.tr("Remove demo data"),
        parent.tr("Delete all demo rolls, prints and cameras? Your own records are kept."),
    )
    if btn != QMessageBox.StandardButton.Yes:
        return False
    res = demo.remove_demo(ctx.session)
    QMessageBox.information(
        parent,
        parent.tr("Demo data"),
        parent.tr("Removed {0} roll(s), {1} print(s), {2} camera(s).").format(
            res.rolls, res.prints, res.cameras
        ),
    )
    return True
