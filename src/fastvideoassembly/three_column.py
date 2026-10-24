"""Three-column assembler tab; portrait eligibility is local to this assembler."""

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .assembly import balance

COLUMN_NAMES = ("Left", "Center", "Right")


class ThreeColumnAssembly(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.tracks = [[], [], []]
        self.active_column = 0
        layout = QVBoxLayout(self)
        output_strip = QHBoxLayout()
        self.column_headers = []
        for index, name in enumerate(COLUMN_NAMES):
            label = QLabel(f"{index + 1} · {name}\n⅓ of output · 640 × 1080")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMargin(12)
            output_strip.addWidget(label, 1)
            self.column_headers.append(label)
        layout.addLayout(output_strip)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.timeline = pg.PlotWidget()
        self.timeline.setAccessibleName(
            "Three tracks with a shared time axis in seconds"
        )
        self.timeline.setMinimumHeight(180)
        self.timeline.setLabel("bottom", "Time", units="s")
        self.timeline.getAxis("left").setTicks(
            [[(2 - index, f"{name} · ⅓") for index, name in enumerate(COLUMN_NAMES)]]
        )
        self.timeline.setMouseEnabled(x=True, y=False)
        self.timeline.setMenuEnabled(False)
        self.timeline.hideButtons()
        self.timeline.scene().sigMouseClicked.connect(controller.timeline_clicked)
        self.splitter.addWidget(self.timeline)
        editor = QWidget()
        editors = QHBoxLayout(editor)
        self.lists = []
        self.track_labels = []
        for column, name in enumerate(COLUMN_NAMES):
            panel = QVBoxLayout()
            label = QLabel(name)
            self.track_labels.append(label)
            panel.addWidget(label)
            listing = QListWidget()
            listing.setAccessibleName(f"{name} column clip order")
            listing.currentRowChanged.connect(
                lambda row, column=column: controller.select_column(column, row)
            )
            listing.itemClicked.connect(
                lambda item: controller.select_clip(item.data(Qt.ItemDataRole.UserRole))
            )
            listing.itemDoubleClicked.connect(controller.open_source)
            self.lists.append(listing)
            panel.addWidget(listing)
            editors.addLayout(panel, 1)
        self.splitter.addWidget(editor)
        self.splitter.setSizes([240, 300])
        layout.addWidget(self.splitter, 1)
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
        self.left_button = QPushButton("Move to left column")
        self.left_button.clicked.connect(lambda: controller.move_column(-1))
        self.right_button = QPushButton("Move to right column")
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
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        export_row = QHBoxLayout()
        self.create_button = QPushButton("Create Timelines")
        self.create_button.setProperty("buttonSize", "large")
        self.create_button.clicked.connect(controller.rebalance)
        export_row.addWidget(self.create_button)
        self.export_button = QPushButton("Render Column Assembly")
        self.export_button.setProperty("variant", "primary")
        self.export_button.setProperty("buttonSize", "large")
        self.export_button.clicked.connect(controller.choose_export)
        export_row.addWidget(self.export_button, 1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setProperty("buttonSize", "large")
        self.stop_button.clicked.connect(controller.stop_export)
        export_row.addWidget(self.stop_button)
        layout.addLayout(export_row)

    def rebalance(self, clips, longest_first=False):
        self.tracks = balance(
            [clip for clip in clips if clip.portrait], longest_first=longest_first
        )
