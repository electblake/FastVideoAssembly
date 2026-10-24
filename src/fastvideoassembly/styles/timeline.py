import pyqtgraph as pg
from PySide6.QtWidgets import QApplication


class TimelineClipStyle:
    @staticmethod
    def apply(item, active):
        item.setProperty("active", active)
        palette = QApplication.palette()
        brush = palette.highlight().color()
        brush.setAlpha(255 if active else (190 if item.index % 2 == 0 else 110))
        item.setOpts(brush=brush, pen=pg.mkPen(palette.text().color(), width=3 if active else 1))


class TimelineTrackStyle:
    @staticmethod
    def apply(item, selected):
        item.setProperty("selected", selected)
        color = QApplication.palette().highlight().color()
        color.setAlpha(28 if selected else 0)
        border = QApplication.palette().highlight().color()
        border.setAlpha(110)
        item.setOpts(brush=color, pen=pg.mkPen(border) if selected else pg.mkPen(None))
