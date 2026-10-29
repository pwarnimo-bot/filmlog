"""Render the SVG app icon to hicolor PNG sizes (run after editing the SVG).

uv run python packaging/icons/render_pngs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def main() -> int:
    app = QGuiApplication(sys.argv[:1])  # noqa: F841 - needed for painting
    here = Path(__file__).parent
    renderer = QSvgRenderer(str(here / "hicolor/scalable/apps/filmlog.svg"))
    for size in SIZES:
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p)
        p.end()
        out = here / f"hicolor/{size}x{size}/apps/filmlog.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out))
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
