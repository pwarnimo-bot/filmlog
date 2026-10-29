"""Generic Qt table model over a list of Python objects, with a live filter proxy."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from filmlog.services.settings import Settings

AnyIndex = QModelIndex | QPersistentModelIndex
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
OBJECT_ROLE = Qt.ItemDataRole.UserRole + 2


@dataclass
class Column:
    header: str
    text: Callable[[Any], Any]
    sort: Callable[[Any], Any] | None = None
    align_right: bool = False
    width: int | None = None
    tooltip: Callable[[Any], str] | None = None
    foreground: Callable[[Any], QColor | None] | None = None


class ObjectTableModel(QAbstractTableModel):
    def __init__(self, columns: Sequence[Column], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self.items: list[Any] = []
        self.dimmed: Callable[[Any], bool] | None = None

    def set_items(self, items: Sequence[Any]) -> None:
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent: AnyIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.columns)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section].header
        return None

    def data(self, index: AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        obj = self.items[index.row()]
        col = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            value = col.text(obj)
            return "" if value is None else str(value)
        if role == SORT_ROLE:
            key = col.sort(obj) if col.sort else col.text(obj)
            if key is None:
                return ""
            return key.lower() if isinstance(key, str) else key
        if role == OBJECT_ROLE:
            return obj
        if role == Qt.ItemDataRole.TextAlignmentRole and col.align_right:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and col.tooltip:
            return col.tooltip(obj)
        if role == Qt.ItemDataRole.ForegroundRole:
            if col.foreground and (c := col.foreground(obj)) is not None:
                return QBrush(c)
            if self.dimmed and self.dimmed(obj):
                return QBrush(QColor(128, 128, 128))
        return None

    def object_at(self, row: int) -> Any:
        return self.items[row]

    def row_of(self, obj: Any) -> int:
        for i, o in enumerate(self.items):
            if o is obj:
                return i
        return -1


class FilterProxy(QSortFilterProxyModel):
    """Case-insensitive "all words must match somewhere in the row" filter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._words: list[str] = []
        self.setSortRole(SORT_ROLE)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.extra_filter: Callable[[Any], bool] | None = None

    def set_text(self, text: str) -> None:
        self._words = [w.lower() for w in text.split() if w]
        self.refilter()

    def refilter(self) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt >= 6.10
            self.beginFilterChange()
            self.endFilterChange()
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: AnyIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        assert isinstance(model, ObjectTableModel)
        obj = model.object_at(row)
        if self.extra_filter is not None and not self.extra_filter(obj):
            return False
        if not self._words:
            return True
        hay = " ".join(
            str(model.data(model.index(row, c, parent)) or "") for c in range(model.columnCount())
        ).lower()
        return all(w in hay for w in self._words)

    def lessThan(self, left: AnyIndex, right: AnyIndex) -> bool:  # noqa: N802
        a = left.data(SORT_ROLE)
        b = right.data(SORT_ROLE)
        try:
            return bool(a < b)
        except TypeError:
            return str(a) < str(b)


class ObjectTable(QTableView):
    """Sortable table whose header state is remembered in settings."""

    def __init__(
        self,
        name: str,
        columns: Sequence[Column],
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.settings = settings
        self.source = ObjectTableModel(columns, self)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.source)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 10)
        header = self.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        for i, col in enumerate(columns):
            if col.width:
                self.setColumnWidth(i, col.width)
            act = QAction(col.header, header)
            act.setCheckable(True)
            act.setChecked(True)
            act.toggled.connect(lambda on, i=i: self.setColumnHidden(i, not on))
            header.addAction(act)
        self._column_actions = header.actions()
        self.delete_action = QAction(self.tr("Delete"), self)
        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.delete_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.addAction(self.delete_action)
        self.restore_state()

    # -- data --------------------------------------------------------------

    def set_items(self, items: Sequence[Any], keep: Any = None) -> None:
        current = keep if keep is not None else self.current_object()
        self.source.set_items(items)
        if current is not None:
            self.select_object(current)

    def current_object(self) -> Any:
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        return self.proxy.mapToSource(rows[0]).data(OBJECT_ROLE)

    def select_object(self, obj: Any) -> bool:
        row = self.source.row_of(obj)
        if row < 0:
            # Fall back to identity by primary key.
            oid = getattr(obj, "id", None)
            for i, o in enumerate(self.source.items):
                if oid is not None and getattr(o, "id", None) == oid:
                    row = i
                    break
        if row < 0:
            return False
        idx = self.proxy.mapFromSource(self.source.index(row, 0))
        if not idx.isValid():
            return False
        self.setCurrentIndex(idx)
        self.scrollTo(idx)
        return True

    def objects(self) -> list[Any]:
        return [
            self.proxy.mapToSource(self.proxy.index(r, 0)).data(OBJECT_ROLE)
            for r in range(self.proxy.rowCount())
        ]

    # -- state -------------------------------------------------------------

    def restore_state(self) -> None:
        state = self.settings.table_states.get(self.name)
        if state:
            self.horizontalHeader().restoreState(QByteArray.fromBase64(state.encode()))
            for i, act in enumerate(self._column_actions):
                act.setChecked(not self.isColumnHidden(i))
        else:
            self.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def save_state(self) -> None:
        data = self.horizontalHeader().saveState().toBase64().data()
        self.settings.table_states[self.name] = bytes(data).decode()
