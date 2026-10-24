"""Column assembler tab; portrait eligibility is local to this assembler."""

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .assembly import balance
from .timeline import TRACK_HEIGHT, move_clips


class TimelineSegment(pg.BarGraphItem):
    def __init__(self, controller, column, index, **options):
        super().__init__(**options)
        self.setFlag(self.GraphicsItemFlag.ItemClipsChildrenToShape)
        self.controller = controller
        self.column = column
        self.index = index

    def hoverEvent(self, event):
        if not self.controller.running and not self.controller.loading:
            event.acceptDrags(Qt.MouseButton.LeftButton)

    def mouseDragEvent(self, event):
        controller = self.controller
        if event.button() != Qt.MouseButton.LeftButton or controller.running or controller.loading:
            event.ignore()
            return
        event.accept()
        assembler = controller.assembler
        timeline = assembler.timeline
        track = assembler.tracks[self.column]
        y = assembler.columns.currentData() - 1 - self.column % assembler.columns.currentData()
        _column, start, end, _y = assembler.track_bounds[self.column]
        if event.isStart():
            selected = controller.selected_clips
            controller.select_clip(track[self.index], sync_source=track[self.index] not in selected)
            self.dragged_clips = controller.selected_clips
            self.marker = pg.PlotCurveItem(pen=pg.mkPen(QApplication.palette().text().color(), width=3))
            timeline.addItem(self.marker, ignoreBounds=True)
        point = timeline.getViewBox().mapSceneToView(event.scenePos())
        valid = abs(point.y() - y) <= TRACK_HEIGHT / 2 and start <= point.x() <= end
        reordered, position = move_clips(track, self.dragged_clips, point.x() - start, controller.render_config())
        self.marker.setData([start + position] * 2, [y - 0.4, y + 0.4])
        self.marker.setVisible(valid)
        if event.isFinish():
            timeline.removeItem(self.marker)
            if valid and reordered != track:
                track[:] = reordered
                controller.finish_timeline_edit()


class ThreeColumnAssembly(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.columns = QComboBox()
        self.columns.addItem("3", 3)
        self.columns.addItem("4", 4)
        self.columns.setCurrentIndex(self.columns.findData(controller.settings.value("assembly/columns", 3, type=int)))
        self.columns.setAccessibleName("Columns")
        self.divisions = QSpinBox()
        self.divisions.setRange(1, 100)
        self.divisions.setValue(controller.settings.value("assembly/divisions", 1, type=int))
        self.divisions.setAccessibleName("Divisions")
        self.tracks = [[] for _ in range(self.columns.currentData() * self.divisions.value())]
        self.selected_timelines = set()
        layout = QVBoxLayout(self)
        self.timeline = pg.PlotWidget()
        self.timeline.setAccessibleName(
            "Timelines with a shared time axis in seconds"
        )
        self.timeline.setLabel("bottom", "Time", units="s")
        self.timeline.getAxis("left").setTicks([])
        self.timeline.setMouseEnabled(x=True, y=False)
        self.timeline.setMenuEnabled(False)
        self.timeline.hideButtons()
        self.timeline.scene().sigMouseClicked.connect(controller.timeline_clicked)
        layout.addWidget(self.timeline, 1)
        self.timelines_group = QGroupBox("Timelines (All)")
        ordering_buttons = QGridLayout(self.timelines_group)
        self.balance_button = QPushButton("Shortest First")
        self.balance_button.clicked.connect(controller.sort_timelines)
        ordering_buttons.addWidget(self.balance_button, 0, 0)
        self.longest_button = QPushButton("Longest First")
        self.longest_button.clicked.connect(
            lambda: controller.sort_timelines(longest_first=True)
        )
        ordering_buttons.addWidget(self.longest_button, 0, 1)
        self.shuffle_button = QPushButton("Shuffle")
        self.shuffle_button.clicked.connect(controller.shuffle_timelines)
        ordering_buttons.addWidget(self.shuffle_button, 1, 0)
        self.select_no_timelines_button = QPushButton("Select None")
        self.select_no_timelines_button.clicked.connect(controller.clear_timeline_selection)
        ordering_buttons.addWidget(self.select_no_timelines_button, 1, 1)
        layout.addWidget(self.timelines_group)
        self.clips_group = QGroupBox("Clips (0)")
        clip_buttons = QGridLayout(self.clips_group)
        self.forward_button = QPushButton("Move Forward")
        self.forward_button.clicked.connect(lambda: controller.move_selected_clips("forward"))
        self.backward_button = QPushButton("Move Backward")
        self.backward_button.clicked.connect(lambda: controller.move_selected_clips("backward"))
        self.start_button = QPushButton("Move to Start")
        self.start_button.clicked.connect(lambda: controller.move_selected_clips("start"))
        self.end_button = QPushButton("Move to End")
        self.end_button.clicked.connect(lambda: controller.move_selected_clips("end"))
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(controller.remove_selected_clip)
        self.select_none_button = QPushButton("Select None")
        self.select_none_button.clicked.connect(controller.library.clearSelection)
        for index, button in enumerate(
            (
                self.forward_button,
                self.backward_button,
                self.start_button,
                self.end_button,
            )
        ):
            clip_buttons.addWidget(button, 0, index)
        clip_buttons.addWidget(self.select_none_button, 1, 0, 1, 2)
        clip_buttons.addWidget(self.remove_button, 1, 2, 1, 2)
        layout.addWidget(self.clips_group)
        final_row = QGridLayout()
        final_row.addWidget(controller.combine, 0, 0)
        final_row.addWidget(QLabel("Columns"), 0, 1)
        final_row.addWidget(self.columns, 0, 2)
        final_row.addWidget(QLabel("Divisions"), 0, 3)
        final_row.addWidget(self.divisions, 0, 4)
        self.remove_timelines = QCheckBox("Delete timelines after final render")
        self.remove_timelines.setChecked(controller.settings.value("assembly/removeTimelines", False, type=bool))
        self.remove_timelines.toggled.connect(
            lambda checked: controller.settings.setValue("assembly/removeTimelines", checked)
        )
        final_row.addWidget(self.remove_timelines, 1, 0, 1, 5)
        controller.combine.toggled.connect(controller.update_enabled)
        final_row.setColumnStretch(5, 1)
        layout.addLayout(final_row)
        self.divisions.valueChanged.connect(controller.divisions_changed)
        self.columns.currentIndexChanged.connect(controller.columns_changed)
        self.keep_logs = QCheckBox("Keep logs between runs")
        layout.addWidget(self.keep_logs)
        export_row = QGridLayout()
        self.create_button = QPushButton("Create Timelines")
        self.create_button.setProperty("buttonSize", "large")
        self.create_button.clicked.connect(controller.create_timelines)
        export_row.addWidget(self.create_button, 0, 0)
        self.scan_pause_button = QPushButton("Pause")
        self.scan_pause_button.setProperty("buttonSize", "large")
        self.scan_pause_button.setAccessibleName("Pause or resume timeline scanning")
        self.scan_pause_button.setToolTip("Pause after active scans finish.")
        self.scan_pause_button.clicked.connect(controller.pause_scanning)
        export_row.addWidget(self.scan_pause_button, 0, 1)
        self.scan_stop_button = QPushButton("Stop")
        self.scan_stop_button.setProperty("buttonSize", "large")
        self.scan_stop_button.setAccessibleName("Stop timeline scanning")
        self.scan_stop_button.setToolTip("Stop after active scans finish. Create Timelines to continue.")
        self.scan_stop_button.clicked.connect(controller.stop_scanning)
        export_row.addWidget(self.scan_stop_button, 0, 2)
        self.export_button = QPushButton("Render")
        self.export_button.setProperty("variant", "primary")
        self.export_button.setProperty("buttonSize", "large")
        self.export_button.clicked.connect(controller.choose_export)
        export_row.addWidget(self.export_button, 1, 0)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setProperty("buttonSize", "large")
        self.pause_button.setAccessibleName("Pause or resume rendering")
        self.pause_button.setToolTip("Pause after the active render or audio analysis batch finishes.")
        self.pause_button.clicked.connect(controller.pause_export)
        export_row.addWidget(self.pause_button, 1, 1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setProperty("buttonSize", "large")
        self.stop_button.setAccessibleName("Stop rendering")
        self.stop_button.clicked.connect(controller.stop_export)
        export_row.addWidget(self.stop_button, 1, 2)
        export_row.setColumnStretch(0, 1)
        layout.addLayout(export_row)

    def rebalance(self, clips, longest_first=False):
        self.tracks = balance(
            [clip for clip in clips if clip.portrait], longest_first=longest_first,
            track_count=self.columns.currentData() * self.divisions.value()
        )
