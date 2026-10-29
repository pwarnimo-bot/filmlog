# SPDX-FileCopyrightText: 2026 Pol Warnimont
# SPDX-License-Identifier: GPL-3.0-or-later

"""Statistics view: a few simple charts (QtCharts if available, else tables)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from filmlog.services.stats import compute
from filmlog.ui.base_view import BaseView
from filmlog.ui.context import AppContext
from filmlog.ui.theme import accent_colour
from filmlog.ui.widgets import push_pull_badge

try:
    from PySide6.QtCharts import (
        QBarCategoryAxis,
        QBarSeries,
        QBarSet,
        QChart,
        QChartView,
        QHorizontalBarSeries,
        QValueAxis,
    )

    HAVE_CHARTS = True
except ImportError:  # e.g. distro PySide6 without the QtCharts module
    HAVE_CHARTS = False


def _chart(title: str, data: list[tuple[str, int]], horizontal: bool) -> QWidget:
    if not HAVE_CHARTS:
        table = QTableWidget(len(data), 2)
        table.setHorizontalHeaderLabels([title, "#"])
        for i, (k, v) in enumerate(data):
            table.setItem(i, 0, QTableWidgetItem(k))
            table.setItem(i, 1, QTableWidgetItem(str(v)))
        table.resizeColumnsToContents()
        return table
    pal = QWidget().palette()
    bars = QBarSet(title)
    bars.setColor(accent_colour())
    bars.setBorderColor(accent_colour())
    labels = [k for k, _ in data]
    values = [v for _, v in data]
    if horizontal:
        labels.reverse()
        values.reverse()
    for v in values:
        bars.append(v)
    series = QHorizontalBarSeries() if horizontal else QBarSeries()
    series.append(bars)
    series.setLabelsVisible(True)
    chart = QChart()
    chart.addSeries(series)
    chart.setTitle(title)
    chart.legend().hide()
    chart.setBackgroundBrush(pal.base())
    chart.setTitleBrush(pal.text())
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
    cats = QBarCategoryAxis()
    cats.append(labels)
    cats.setLabelsBrush(pal.text())
    vals = QValueAxis()
    vals.setLabelFormat("%d")
    # Whole-number ticks, at most 6 of them.
    top = max(values + [1])
    step = -(-top // 5)
    ticks = -(-top // step)
    vals.setRange(0, step * ticks)
    vals.setTickCount(ticks + 1)
    vals.setLabelsBrush(pal.text())
    for axis in (cats, vals):
        axis.setGridLineColor(pal.mid().color())
        axis.setLinePenColor(pal.mid().color())
    if horizontal:
        chart.addAxis(cats, Qt.AlignmentFlag.AlignLeft)
        chart.addAxis(vals, Qt.AlignmentFlag.AlignBottom)
    else:
        chart.addAxis(cats, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(vals, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(cats)
    series.attachAxis(vals)
    view = QChartView(chart)
    view.setRenderHint(QPainter.RenderHint.Antialiasing)
    view.setMinimumHeight(max(260, 90 + 34 * len(data)) if horizontal else 260)
    return view


class StatisticsView(BaseView):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.title = self.tr("Statistics")
        self.summary = QLabel()
        self.summary.setProperty("role", "page-title")
        self.grid = QGridLayout()
        body = QWidget()
        v = QVBoxLayout(body)
        v.addWidget(self.summary)
        v.addLayout(self.grid)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)
        layout = QHBoxLayout(self)
        layout.addWidget(scroll)

    def refresh(self) -> None:
        st = compute(self.ctx.session)
        self.summary.setText(
            self.tr("{0} rolls · {1} prints ({2} final)").format(
                st.total_rolls, st.total_prints, st.final_prints
            )
        )
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        if not st.total_rolls:
            self.grid.addWidget(QLabel(self.tr("No rolls yet — statistics appear here later.")))
            return
        push_pull = [(push_pull_badge(stops)[0], n) for stops, n in st.push_pull]
        charts = [
            (self.tr("Rolls per year"), st.rolls_per_year, False),
            (self.tr("Push / pull"), push_pull, False),
            (self.tr("Most used films"), st.top_films, True),
            (self.tr("Most used developers"), st.top_developers, True),
            (self.tr("Most used cameras"), st.top_cameras, True),
        ]
        for i, (title, data, horizontal) in enumerate(charts):
            if data:
                self.grid.addWidget(_chart(title, data, horizontal), i // 2, i % 2)
