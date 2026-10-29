"""Thumbnails and image-picking widgets (drag & drop or file picker)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QImageReader,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from filmlog import paths
from filmlog.services.images import IMAGE_EXTENSIONS, image_path, import_image, is_image_file
from filmlog.ui.theme import current_theme

AnyIndex = QModelIndex | QPersistentModelIndex
_cache: dict[tuple[str, int, str], QPixmap] = {}


def _darkroom_tint(img: QImage) -> QImage:
    """Dim red monochrome version for the Darkroom theme (no bright white light)."""
    gray = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
        QImage.Format.Format_RGB32
    )
    out = QImage(gray.size(), QImage.Format.Format_RGB32)
    out.fill(QColor(0, 0, 0))
    p = QPainter(out)
    p.setOpacity(0.35)
    p.drawImage(0, 0, gray)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    p.setOpacity(1.0)
    p.fillRect(out.rect(), QColor(255, 0, 0))
    p.end()
    return out


def load_thumbnail(name: str | None, size: int = 160) -> QPixmap | None:
    """Thumbnail for an image in the images folder (cached on disk and in memory)."""
    if not name:
        return None
    theme = "darkroom" if current_theme() == "darkroom" else "normal"
    key = (name, size, theme)
    if key in _cache:
        return _cache[key]
    src = image_path(name)
    if not src.is_file():
        return None
    thumb_file = paths.thumbnails_dir() / f"{Path(name).stem}_{size}.png"
    img = QImage()
    if thumb_file.is_file() and thumb_file.stat().st_mtime >= src.stat().st_mtime:
        img.load(str(thumb_file))
    if img.isNull():
        reader = QImageReader(str(src))
        reader.setAutoTransform(True)
        full = reader.size()
        if full.isValid():
            reader.setScaledSize(full.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio))
        img = reader.read()
        if img.isNull():
            return None
        thumb_file.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(thumb_file))
    if theme == "darkroom":
        img = _darkroom_tint(img)
    pm = QPixmap.fromImage(img)
    _cache[key] = pm
    return pm


def forget_thumbnail(name: str | None) -> None:
    for k in [k for k in _cache if k[0] == name]:
        del _cache[k]


def open_image(name: str | None) -> None:
    if name:
        p = image_path(name)
        if p.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def image_filter() -> str:
    pattern = " ".join(f"*{e}" for e in IMAGE_EXTENSIONS)
    return f"Images ({pattern})"


def pick_image_files(parent: QWidget, multiple: bool = False) -> list[Path]:
    title = parent.tr("Choose image")
    if multiple:
        files, _ = QFileDialog.getOpenFileNames(parent, title, str(Path.home()), image_filter())
        return [Path(f) for f in files]
    f, _ = QFileDialog.getOpenFileName(parent, title, str(Path.home()), image_filter())
    return [Path(f)] if f else []


def dropped_images(event: QDropEvent | QDragEnterEvent) -> list[Path]:
    md = event.mimeData()
    if not md.hasUrls():
        return []
    return [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()
            and is_image_file(Path(u.toLocalFile()))]  # fmt: skip


class ImageField(QFrame):
    """Single image slot: thumbnail, drop target, Choose / Remove / Open.

    Files are copied into the images folder immediately; the caller deletes
    files that end up unreferenced after save/cancel.
    """

    changed = Signal()

    def __init__(self, size: int = 180, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._size = size
        self._name: str | None = None
        self.imported: list[str] = []  # files copied in during this edit
        self.thumb = QLabel()
        self.thumb.setFixedSize(size, int(size * 0.75))
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setWordWrap(True)
        self.choose = QPushButton(self.tr("Choose…"))
        self.choose.clicked.connect(self._choose)
        self.remove = QPushButton(self.tr("Remove"))
        self.remove.clicked.connect(lambda: self.set_name(None, user=True))
        self.open = QPushButton(self.tr("Open"))
        self.open.clicked.connect(lambda: open_image(self._name))
        buttons = QVBoxLayout()
        for b in (self.choose, self.remove, self.open):
            buttons.addWidget(b)
        buttons.addStretch(1)
        h = QHBoxLayout(self)
        h.addWidget(self.thumb)
        h.addLayout(buttons)
        h.addStretch(1)
        self._render()

    def name(self) -> str | None:
        return self._name

    def set_name(self, name: str | None, *, user: bool = False) -> None:
        self._name = name
        if not user:
            self.imported = []
        self._render()
        if user:
            self.changed.emit()

    def _render(self) -> None:
        pm = load_thumbnail(self._name, self._size)
        if pm is not None:
            self.thumb.setPixmap(pm)
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText(
                self.tr("Drop an image here") if not self._name else self.tr("(missing file)")
            )
        self.remove.setEnabled(self._name is not None)
        self.open.setEnabled(self._name is not None)

    def _add(self, src: Path) -> None:
        name = import_image(src)
        self.imported.append(name)
        self.set_name(name, user=True)

    def _choose(self) -> None:
        files = pick_image_files(self)
        if files:
            self._add(files[0])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if dropped_images(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        files = dropped_images(event)
        if files:
            self._add(files[0])
            event.acceptProposedAction()


class ThumbListModel(QAbstractListModel):
    """(file name, caption) items shown as thumbnails."""

    def __init__(self, size: int = 140, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.size = size
        self.items: list[tuple[str, str, object]] = []

    def set_items(self, items: list[tuple[str, str, object]]) -> None:
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        name, caption, obj = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return caption
        if role == Qt.ItemDataRole.DecorationRole:
            return load_thumbnail(name, self.size)
        if role == Qt.ItemDataRole.ToolTipRole:
            return caption or name
        if role == Qt.ItemDataRole.UserRole:
            return obj
        return None


class ThumbGrid(QListView):
    """Icon-mode list of thumbnails that accepts dropped image files."""

    filesDropped = Signal(list)  # noqa: N815

    def __init__(self, size: int = 140, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.thumbs = ThumbListModel(size, self)
        self.setModel(self.thumbs)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 24, size + 44))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setSpacing(6)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListView.DragDropMode.DropOnly)

    def current_obj(self) -> object:
        idx = self.currentIndex()
        return idx.data(Qt.ItemDataRole.UserRole) if idx.isValid() else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if dropped_images(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]  # noqa: N802
        if dropped_images(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        files = dropped_images(event)
        if files:
            self.filesDropped.emit(files)
            event.acceptProposedAction()
