"""Roll detail tabs: Prints (cards) and Images (contact sheet + scans)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListView,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from filmlog.db.models import Print, Roll, RollImage
from filmlog.services.images import delete_unreferenced, import_image
from filmlog.services.prints import contrast_summary, duplicate_print, total_exposure
from filmlog.services.timefmt import format_seconds
from filmlog.ui.context import AppContext
from filmlog.ui.images import ImageField, ThumbGrid, load_thumbnail, open_image, pick_image_files
from filmlog.ui.print_form import PrintDialog
from filmlog.ui.widgets import chip_colours, stars

AnyIndex = QModelIndex | QPersistentModelIndex
CARD_W, CARD_H, THUMB = 360, 108, 92


def _tr(text: str) -> str:
    return QCoreApplication.translate("RollTabs", text)


def print_card_lines(p: Print) -> list[str]:
    paper = p.paper.display_name if p.paper else _tr("unknown paper")
    if p.paper_size:
        paper += f", {p.paper_size}"
    total = format_seconds(total_exposure(p.exposures))
    return [
        _tr("Frame {0}").format(p.frame or "?") + (f" — {p.title}" if p.title else ""),
        paper,
        contrast_summary(p.contrast_method, p.exposures) + f"  ·  {_tr('total')} {total}",
        f"{stars(p.rating)}  {p.date_printed or ''}".strip(),
    ]


class PrintCardDelegate(QStyledItemDelegate):
    def sizeHint(self, option: QStyleOptionViewItem, index: AnyIndex) -> QSize:  # noqa: N802
        return QSize(CARD_W, CARD_H)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        p = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(p, Print):
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = option.palette
        rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(pal.highlight().color() if selected else pal.mid().color())
        painter.setBrush(pal.base())
        painter.drawRoundedRect(rect, 6, 6)

        thumb_rect = QRect(rect.left() + 8, rect.top() + 6, THUMB, rect.height() - 12)
        pm = load_thumbnail(p.image, 160)
        if pm is not None:
            scaled = pm.scaled(thumb_rect.size(), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)  # fmt: skip
            x = thumb_rect.left() + (thumb_rect.width() - scaled.width()) // 2
            y = thumb_rect.top() + (thumb_rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal.alternateBase())
            painter.drawRoundedRect(thumb_rect, 4, 4)
            painter.setPen(pal.placeholderText().color())
            painter.drawText(thumb_rect, int(Qt.AlignmentFlag.AlignCenter), _tr("no image"))

        text_rect = QRect(thumb_rect.right() + 10, rect.top() + 6,
                          rect.right() - thumb_rect.right() - 16, rect.height() - 12)  # fmt: skip
        lines = print_card_lines(p)
        fm = option.fontMetrics
        y = text_rect.top()
        for i, line in enumerate(lines):
            font = QFont(option.font)
            font.setBold(i == 0)
            painter.setFont(font)
            painter.setPen(pal.text().color())
            elided = fm.elidedText(line, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(text_rect.left(), y + fm.ascent(), elided)
            y += fm.height() + 3

        label = _tr("Final") if p.is_final else _tr("Work print")
        bg, fg = chip_colours("final" if p.is_final else "box")
        font = QFont(option.font)
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        font.setBold(True)
        painter.setFont(font)
        w = painter.fontMetrics().horizontalAdvance(label) + 14
        h = painter.fontMetrics().height() + 4
        chip = QRect(rect.right() - w - 8, rect.bottom() - h - 6, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(chip, h / 2, h / 2)
        painter.setPen(QColor(fg))
        painter.drawText(chip, int(Qt.AlignmentFlag.AlignCenter), label)
        painter.restore()


class PrintsTab(QWidget):
    """The roll's prints as cards, with Add / Duplicate / Edit / Delete."""

    changed = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.roll: Roll | None = None
        self.grid = ThumbGrid(THUMB)
        self.grid.setViewMode(QListView.ViewMode.ListMode)
        self.grid.setFlow(QListView.Flow.LeftToRight)
        self.grid.setWrapping(True)
        self.grid.setGridSize(QSize())
        self.grid.setItemDelegate(PrintCardDelegate(self.grid))
        self.grid.setAcceptDrops(False)
        self.grid.doubleClicked.connect(lambda _: self.edit_print())
        self.grid.activated.connect(lambda _: self.edit_print())

        self.add_btn = QPushButton(_tr("Add print"))
        self.add_btn.setProperty("role", "primary")
        self.dup_btn = QPushButton(_tr("Duplicate print"))
        self.dup_btn.setToolTip(_tr("New print with all settings copied — only tweak what changed"))
        self.edit_btn = QPushButton(_tr("Edit"))
        self.del_btn = QPushButton(_tr("Delete"))
        self.add_btn.clicked.connect(self.add_print)
        self.dup_btn.clicked.connect(self.duplicate_print)
        self.edit_btn.clicked.connect(self.edit_print)
        self.del_btn.clicked.connect(self.delete_print)
        delete = QShortcut(QKeySequence.StandardKey.Delete, self.grid)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.delete_print)
        self.summary = QLabel()
        bar = QHBoxLayout()
        bar.addWidget(self.summary, 1)
        for b in (self.add_btn, self.dup_btn, self.edit_btn, self.del_btn):
            bar.addWidget(b)
        v = QVBoxLayout(self)
        v.addLayout(bar)
        v.addWidget(self.grid, 1)
        self.grid.selectionModel().currentChanged.connect(lambda *_: self._update_buttons())

    def set_roll(self, roll: Roll | None) -> None:
        self.roll = roll
        self.reload()

    def reload(self, select: Print | None = None) -> None:
        prints = list(self.roll.prints) if self.roll is not None and self.roll.id else []
        self.grid.thumbs.set_items([(p.image or "", "", p) for p in prints])
        finals = sum(1 for p in prints if p.is_final)
        self.summary.setText(
            _tr("{0} print(s), {1} final").format(len(prints), finals) if prints else
            _tr("No prints yet. “Add print” records your first one.")
        )  # fmt: skip
        if select is not None and select in prints:
            self.grid.setCurrentIndex(self.grid.thumbs.index(prints.index(select)))
        self._update_buttons()

    def current(self) -> Print | None:
        obj = self.grid.current_obj()
        return obj if isinstance(obj, Print) else None

    def _update_buttons(self) -> None:
        has_roll = self.roll is not None and self.roll.id is not None
        self.add_btn.setEnabled(has_roll)
        for b in (self.dup_btn, self.edit_btn, self.del_btn):
            b.setEnabled(self.current() is not None)

    def _run_dialog(self, p: Print | None, note: str = "") -> None:
        dlg = PrintDialog(self.ctx, self)
        if p is None:
            dlg.form.load_new(self.roll)
        else:
            dlg.form.fixed_roll = self.roll
            dlg.form.load_print(p, note)
        if dlg.exec():
            obj = dlg.form.obj
            self.reload(select=obj if isinstance(obj, Print) else None)
            self.changed.emit()

    def add_print(self) -> None:
        if self.roll is not None and self.roll.id is not None:
            self._run_dialog(None)

    def duplicate_print(self) -> None:
        src = self.current()
        if src is None:
            return
        copy = duplicate_print(src)
        self._run_dialog(
            copy,
            _tr("Duplicate of frame {0} — all settings copied, adjust what changed.").format(
                src.frame or "?"
            ),
        )

    def edit_print(self) -> None:
        p = self.current()
        if p is not None:
            self._run_dialog(p)

    def delete_print(self) -> None:
        p = self.current()
        if p is None:
            return
        extra = _tr("\n\nIts attached image will be deleted too.") if p.image else ""
        btn = QMessageBox.question(
            self,
            _tr("Delete print"),
            _tr("Delete the print of frame {0}?").format(p.frame or "?") + extra,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        image = p.image
        s = self.ctx.session
        if self.roll is not None and p in self.roll.prints:
            self.roll.prints.remove(p)
        s.delete(p)
        s.commit()
        delete_unreferenced(s, [image])
        self.reload()
        self.changed.emit()


class ImagesTab(QWidget):
    """Contact sheet, extra scans (drag & drop), and the roll's print images."""

    changed = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.roll: Roll | None = None
        self.contact = ImageField(220)
        self.contact.changed.connect(self._contact_changed)
        self.scans = ThumbGrid(130)
        self.scans.filesDropped.connect(self._add_files)
        self.scans.doubleClicked.connect(
            lambda idx: open_image(idx.data(Qt.ItemDataRole.UserRole).filename)
        )
        self.add_btn = QPushButton(_tr("Add images…"))
        self.add_btn.clicked.connect(lambda: self._add_files(pick_image_files(self, True)))
        self.remove_btn = QPushButton(_tr("Remove"))
        self.remove_btn.clicked.connect(self._remove_scan)
        self.prints = ThumbGrid(110)
        self.prints.setAcceptDrops(False)
        self.prints.doubleClicked.connect(
            lambda idx: open_image(idx.data(Qt.ItemDataRole.UserRole).image)
        )
        bar = QHBoxLayout()
        bar.addWidget(QLabel(_tr("<b>Scans</b> — drop image files here")), 1)
        bar.addWidget(self.add_btn)
        bar.addWidget(self.remove_btn)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(_tr("<b>Contact sheet</b>")))
        v.addWidget(self.contact)
        v.addLayout(bar)
        v.addWidget(self.scans, 2)
        v.addWidget(QLabel(_tr("<b>Print images</b> (edit them on the Prints tab)")))
        v.addWidget(self.prints, 1)

    def set_roll(self, roll: Roll | None) -> None:
        self.roll = roll
        self.reload()

    def reload(self) -> None:
        roll = self.roll
        ok = roll is not None and roll.id is not None
        self.setEnabled(ok)
        self.contact.set_name(roll.contact_sheet_image if roll is not None and ok else None)
        scans = list(roll.images) if roll is not None and ok else []
        self.scans.thumbs.set_items([(i.filename, i.caption, i) for i in scans])
        prints = [p for p in roll.prints if p.image] if roll is not None and ok else []
        self.prints.thumbs.set_items(
            [(p.image or "", _tr("frame {0}").format(p.frame or "?"), p) for p in prints]
        )

    def _contact_changed(self) -> None:
        if self.roll is None:
            return
        old = self.roll.contact_sheet_image
        self.roll.contact_sheet_image = self.contact.name()
        self.ctx.session.commit()
        delete_unreferenced(self.ctx.session, [old])
        self.contact.imported = []
        self.changed.emit()

    def _add_files(self, files: list[Path]) -> None:
        if self.roll is None or not files:
            return
        pos = len(self.roll.images)
        for i, f in enumerate(files):
            try:
                name = import_image(f)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, _tr("Image"), str(exc))
                continue
            self.roll.images.append(RollImage(filename=name, caption=f.stem, position=pos + i))
        self.ctx.session.commit()
        self.reload()
        self.changed.emit()

    def _remove_scan(self) -> None:
        img = self.scans.current_obj()
        if not isinstance(img, RollImage) or self.roll is None:
            return
        btn = QMessageBox.question(
            self,
            _tr("Remove image"),
            _tr("Remove “{0}” and delete its file?").format(img.caption or img.filename),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if btn != QMessageBox.StandardButton.Yes:
            return
        name = img.filename
        self.roll.images.remove(img)
        self.ctx.session.commit()
        delete_unreferenced(self.ctx.session, [name])
        self.reload()
