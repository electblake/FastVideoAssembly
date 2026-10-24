"""Three-column assembler tab; portrait eligibility is local to this assembler."""

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .assembly import balance


class ThreeColumnAssembly(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.divisions = QSpinBox()
        self.divisions.setRange(1, 100)
        self.divisions.setValue(controller.settings.value("assembly/divisions", 1, type=int))
        self.divisions.setAccessibleName("Divisions")
        self.tracks = [[] for _ in range(3 * self.divisions.value())]
        self.active_column = -1
        self.active_row = -1
        layout = QVBoxLayout(self)
        self.timeline = pg.PlotWidget()
        self.timeline.setAccessibleName(
            "Three tracks with a shared time axis in seconds"
        )
        self.timeline.setMinimumHeight(180)
        self.timeline.setLabel("bottom", "Time", units="s")
        self.timeline.getAxis("left").setTicks([])
        self.timeline.setMouseEnabled(x=True, y=False)
        self.timeline.setMenuEnabled(False)
        self.timeline.hideButtons()
        self.timeline.scene().sigMouseClicked.connect(controller.timeline_clicked)
        layout.addWidget(self.timeline, 1)
        edit_buttons = QGridLayout()
        self.balance_button = QPushButton("Shortest First")
        self.balance_button.clicked.connect(controller.rebalance)
        edit_buttons.addWidget(self.balance_button, 0, 0)
        self.longest_button = QPushButton("Longest First")
        self.longest_button.setToolTip(
            "Balance total column durations, then sort each column from longest to shortest."
        )
        self.longest_button.clicked.connect(
            lambda: controller.rebalance(longest_first=True)
        )
        edit_buttons.addWidget(self.longest_button, 0, 1)
        self.up_button = QPushButton("Move earlier")
        self.up_button.clicked.connect(lambda: controller.reorder(-1))
        self.down_button = QPushButton("Move later")
        self.down_button.clicked.connect(lambda: controller.reorder(1))
        self.left_button = QPushButton("Move to previous timeline")
        self.left_button.clicked.connect(lambda: controller.move_column(-1))
        self.right_button = QPushButton("Move to next timeline")
        self.right_button.clicked.connect(lambda: controller.move_column(1))
        self.remove_button = QPushButton("Remove Selected Clip")
        self.remove_button.clicked.connect(controller.remove_selected_clip)
        edit_buttons.addWidget(self.remove_button, 0, 2, 1, 2)
        for index, button in enumerate(
            (
                self.up_button,
                self.down_button,
                self.left_button,
                self.right_button,
            )
        ):
            edit_buttons.addWidget(button, 1, index)
        layout.addLayout(edit_buttons)
        final_row = QGridLayout()
        final_row.addWidget(controller.combine, 0, 0)
        final_row.addWidget(QLabel("Divisions"), 0, 1)
        final_row.addWidget(self.divisions, 0, 2)
        self.remove_timelines = QCheckBox("Remove timelines after FINAL")
        self.remove_timelines.setChecked(controller.settings.value("assembly/removeTimelines", False, type=bool))
        self.remove_timelines.toggled.connect(
            lambda checked: controller.settings.setValue("assembly/removeTimelines", checked)
        )
        final_row.addWidget(self.remove_timelines, 1, 0, 1, 3)
        controller.combine.toggled.connect(controller.update_enabled)
        final_row.setColumnStretch(3, 1)
        layout.addLayout(final_row)
        self.divisions.valueChanged.connect(controller.divisions_changed)
        export_row = QGridLayout()
        self.create_button = QPushButton("Create Timelines")
        self.create_button.setProperty("buttonSize", "large")
        self.create_button.clicked.connect(controller.create_timelines)
        export_row.addWidget(self.create_button, 0, 0)
        self.scan_pause_button = QPushButton("Pause")
        self.scan_pause_button.setProperty("buttonSize", "large")
        self.scan_pause_button.setAccessibleName("Pause or resume timeline scanning")
        self.scan_pause_button.setToolTip("Finish active scans, then pause. Resume keeps completed scans.")
        self.scan_pause_button.clicked.connect(controller.pause_scanning)
        export_row.addWidget(self.scan_pause_button, 0, 1)
        self.scan_stop_button = QPushButton("Stop")
        self.scan_stop_button.setProperty("buttonSize", "large")
        self.scan_stop_button.setAccessibleName("Stop timeline scanning")
        self.scan_stop_button.setToolTip("Finish active scans and stop. Create Timelines resumes remaining sources.")
        self.scan_stop_button.clicked.connect(controller.stop_scanning)
        export_row.addWidget(self.scan_stop_button, 0, 2)
        self.export_button = QPushButton("Render Column Assembly")
        self.export_button.setProperty("variant", "primary")
        self.export_button.setProperty("buttonSize", "large")
        self.export_button.clicked.connect(controller.choose_export)
        export_row.addWidget(self.export_button, 1, 0)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setProperty("buttonSize", "large")
        self.pause_button.setAccessibleName("Pause or resume rendering")
        self.pause_button.setToolTip("Finish the current render job, then pause. Resume keeps completed jobs.")
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
            track_count=3 * self.divisions.value()
        )
