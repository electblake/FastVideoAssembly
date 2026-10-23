"""Native Qt shell following FastVideoCropper's widget and appearance patterns."""

import json
import sys
import tempfile
from dataclasses import asdict
from datetime import date
from functools import partial
from pathlib import Path
from string import Template

import pyqtgraph as pg
import qt_themes
from platformdirs import user_config_path
from PySide6.QtCore import QEvent, QObject, QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import APP_NAME, APP_VERSION, integrations
from .assembly import (
    RenderConfig,
    balance,
    clip_duration,
    clip_from_probe,
    column_jobs,
    composition_arguments,
    video_paths,
)
from .audio import mix_peak_arguments, peak_measurement_arguments
from .preview import Preview

COLUMN_NAMES = ("Left", "Center", "Right")


def timestamp(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes):02d}:{seconds:04.1f}"


class Application(QObject):
    def __init__(
        self,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        paths=(),
        launcher_module=integrations.APP_MODULE,
    ):
        super().__init__()
        self.native_style = QApplication.style().objectName()
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.launcher_module = launcher_module
        self.settings = QSettings(
            str(user_config_path(APP_NAME, appauthor=False) / "settings.ini"),
            QSettings.Format.IniFormat,
        )
        self.clips = []
        self.tracks = [[], [], []]
        self.pending = []
        self.loading = False
        self.running = False
        self.active_column = 0
        self.selected_clip = None
        self.progress_buffer = ""
        self.output = None
        self.export_directory = None
        self.window = QMainWindow()
        self.window.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.window.resize(1280, 850)
        self.window.setAcceptDrops(True)
        self.window.installEventFilter(self)
        self.probe = QProcess(self)
        self.probe.finished.connect(self.probed)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_progress)
        self.process.readyReadStandardError.connect(self.read_log)
        self.process.finished.connect(self.finished)
        self.build_ui()
        self.apply_appearance()
        if self.settings.contains("mainWindow/geometry"):
            self.window.restoreGeometry(self.settings.value("mainWindow/geometry"))
        if self.settings.contains("mainWindow/state"):
            self.window.restoreState(self.settings.value("mainWindow/state"), 1)
        if self.settings.contains("mainWindow/splitterState"):
            self.splitter.restoreState(self.settings.value("mainWindow/splitterState"))
        self.refresh()
        if paths:
            self.add_paths(paths)

    def build_ui(self):
        file_menu = self.window.menuBar().addMenu("&File")
        self.open_action = QAction("Open &folder…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_folder)
        file_menu.addAction(self.open_action)
        self.clear_action = file_menu.addAction("Clear assembly", self.clear)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.window.close)
        view_menu = self.window.menuBar().addMenu("&View")
        settings_menu = self.window.menuBar().addMenu("&Settings")
        appearance = settings_menu.addMenu("Appearance")
        appearance_widget = QWidget()
        appearance_layout = QVBoxLayout(appearance_widget)
        self.theme = QComboBox()
        self.theme.addItem("System", "")
        for theme in qt_themes.get_themes():
            self.theme.addItem(theme.replace("_", " ").title(), theme)
        self.theme.setCurrentIndex(
            self.theme.findData(self.settings.value("appearance/theme", ""))
        )
        self.icon = QComboBox()
        for path in sorted(Path(__file__).with_name("icons").glob("*.ico")):
            self.icon.addItem(path.stem.title(), path.stem)
        self.icon.setCurrentIndex(
            self.icon.findData(self.settings.value("appearance/icon", "violet"))
        )
        appearance_layout.addWidget(QLabel("Theme"))
        appearance_layout.addWidget(self.theme)
        appearance_layout.addWidget(QLabel("Application icon"))
        appearance_layout.addWidget(self.icon)
        apply = QPushButton("Apply appearance")
        apply.clicked.connect(self.apply_appearance)
        appearance_layout.addWidget(apply)
        appearance_action = QWidgetAction(self.window)
        appearance_action.setDefaultWidget(appearance_widget)
        appearance.addAction(appearance_action)
        help_menu = self.window.menuBar().addMenu("&Help")
        help_menu.addAction("Install in File Explorer", self.install_explorer)

        library_widget = QWidget()
        library_layout = QVBoxLayout(library_widget)
        self.open_button = QPushButton("Open folder…")
        self.open_button.clicked.connect(self.open_folder)
        library_layout.addWidget(self.open_button)
        self.library_summary = QLabel("Choose a folder of videos.")
        self.library_summary.setWordWrap(True)
        library_layout.addWidget(self.library_summary)
        self.library = QListWidget()
        self.library.setAccessibleName("Source videos")
        self.library.currentRowChanged.connect(self.select_source)
        library_layout.addWidget(self.library)
        self.library_dock = QDockWidget("Source videos", self.window)
        self.library_dock.setObjectName("sourceVideos")
        self.library_dock.setWidget(library_widget)
        self.window.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock
        )
        view_menu.addAction(self.library_dock.toggleViewAction())
        self.preview = Preview()
        self.preview_dock = QDockWidget("Preview", self.window)
        self.preview_dock.setObjectName("clipPreview")
        self.preview_dock.setWidget(self.preview)
        self.window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.preview_dock
        )
        view_menu.addAction(self.preview_dock.toggleViewAction())
        self.build_render_settings(view_menu)
        self.window.splitDockWidget(
            self.preview_dock, self.config_dock, Qt.Orientation.Vertical
        )
        self.build_audio_settings(view_menu)
        self.build_output_settings(view_menu)

        central = QWidget()
        layout = QVBoxLayout(central)
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
        self.timeline.scene().sigMouseClicked.connect(self.timeline_clicked)
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
                lambda row, column=column: self.select_column(column, row)
            )
            listing.itemDoubleClicked.connect(self.open_source)
            self.lists.append(listing)
            panel.addWidget(listing)
            editors.addLayout(panel, 1)
        self.splitter.addWidget(editor)
        self.splitter.setSizes([240, 300])
        layout.addWidget(self.splitter, 1)
        edit_buttons = QGridLayout()
        self.balance_button = QPushButton("Shortest First")
        self.balance_button.clicked.connect(self.rebalance)
        edit_buttons.addWidget(self.balance_button, 0, 0)
        self.longest_button = QPushButton("Longest First")
        self.longest_button.setToolTip(
            "Balance total column durations, then sort each column from longest to shortest."
        )
        self.longest_button.clicked.connect(lambda: self.rebalance(longest_first=True))
        edit_buttons.addWidget(self.longest_button, 0, 1)
        self.up_button = QPushButton("Move earlier")
        self.up_button.clicked.connect(lambda: self.reorder(-1))
        self.down_button = QPushButton("Move later")
        self.down_button.clicked.connect(lambda: self.reorder(1))
        self.left_button = QPushButton("Move to left column")
        self.left_button.clicked.connect(lambda: self.move_column(-1))
        self.right_button = QPushButton("Move to right column")
        self.right_button.clicked.connect(lambda: self.move_column(1))
        self.remove_button = QPushButton("Remove Selected Clip")
        self.remove_button.clicked.connect(self.remove_selected_clip)
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
        self.export_button = QPushButton("Render three-column video…")
        self.export_button.setProperty("variant", "primary")
        self.export_button.setProperty("buttonSize", "large")
        self.export_button.clicked.connect(self.choose_export)
        export_row.addWidget(self.export_button, 1)
        self.stop_button = QPushButton("Stop rendering")
        self.stop_button.clicked.connect(self.stop_export)
        export_row.addWidget(self.stop_button)
        layout.addLayout(export_row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        layout.addWidget(self.progress)
        self.window.setCentralWidget(central)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log_dock = QDockWidget("Process log", self.window)
        self.log_dock.setObjectName("processLog")
        self.log_dock.setWidget(self.log)
        self.window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()
        view_menu.addAction(self.log_dock.toggleViewAction())

    def build_render_settings(self, view_menu):
        self.render_panel = QWidget()
        form = QFormLayout(self.render_panel)
        self.resolution = QComboBox()
        self.resolution.addItem("1920 × 1080 (640 × 1080 per column)", [640, 1080])
        self.resolution.addItem("3840 × 2160 (1280 × 2160 per column)", [1280, 2160])
        self.frame_rate = QComboBox()
        for label, value in [
            ("23.976", "24000/1001"),
            ("24", "24"),
            ("25", "25"),
            ("29.97", "30000/1001"),
            ("30", "30"),
            ("60", "60"),
        ]:
            self.frame_rate.addItem(label, value)
        self.encoder = QComboBox()
        self.encoder.addItem("NVIDIA HEVC · 10-bit", "hevc_nvenc")
        self.encoder.addItem("NVIDIA H.264 · 8-bit", "h264_nvenc")
        self.encoder.addItem("CPU H.264 · 8-bit", "libx264")
        self.speed = QComboBox()
        for value in ("fast", "balanced", "quality"):
            self.speed.addItem(value.title(), value)
        self.quality = QSpinBox()
        self.quality.setRange(1, 51)
        self.combine = QCheckBox("Also render the final three-column video")
        saved = RenderConfig()
        if self.settings.contains("render/config"):
            saved = RenderConfig(**json.loads(self.settings.value("render/config")))
        self.resolution.setCurrentIndex(
            self.resolution.findData([saved.column_width, saved.height])
        )
        self.frame_rate.setCurrentIndex(self.frame_rate.findData(saved.fps))
        self.encoder.setCurrentIndex(self.encoder.findData(saved.encoder))
        self.speed.setCurrentIndex(self.speed.findData(saved.speed))
        self.quality.setValue(saved.quality)
        self.combine.setChecked(self.settings.value("render/combine", True, type=bool))
        for title, widget in [
            ("Output size", self.resolution),
            ("Frames / second", self.frame_rate),
            ("Encoder", self.encoder),
            ("Speed / quality", self.speed),
            ("Quality value", self.quality),
        ]:
            form.addRow(title, widget)
            widget.setAccessibleName(title)
        form.addRow(self.combine)
        self.config_dock = QDockWidget("Render Settings", self.window)
        self.config_dock.setObjectName("sharedRenderConfiguration")
        self.config_dock.setWidget(self.render_panel)
        self.window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.config_dock
        )
        view_menu.addAction(self.config_dock.toggleViewAction())
        for combo in (self.resolution, self.frame_rate, self.encoder, self.speed):
            combo.currentIndexChanged.connect(self.render_settings_changed)
        self.quality.valueChanged.connect(self.render_settings_changed)
        self.combine.toggled.connect(self.render_settings_changed)

    def build_audio_settings(self, view_menu):
        self.audio_panel = QWidget()
        layout = QVBoxLayout(self.audio_panel)
        codec_form = QFormLayout()
        self.audio_codec = QComboBox()
        for label, value in (
            ("AAC", "aac"),
            ("MP3", "libmp3lame"),
            ("AC-3", "ac3"),
            ("E-AC-3", "eac3"),
        ):
            self.audio_codec.addItem(label, value)
        self.audio_codec.setAccessibleName("Audio codec")
        self.audio_codec.setCurrentIndex(
            self.audio_codec.findData(self.settings.value("audio/codec", "aac"))
        )
        codec_form.addRow("Codec", self.audio_codec)
        layout.addLayout(codec_form)
        group = QGroupBox("Normalize Audio")
        form = QFormLayout(group)
        self.normalization = QComboBox()
        self.normalization.addItems(["None", "True Peak", "YouTube"])
        self.normalization.setAccessibleName("Normalization mode")
        self.normalization.setCurrentText(
            self.settings.value("audio/normalization", "None")
        )
        form.addRow("Normalization mode", self.normalization)
        layout.addWidget(group)
        layout.addStretch()
        self.audio_dock = QDockWidget("Audio Settings", self.window)
        self.audio_dock.setObjectName("audioSettings")
        self.audio_dock.setWidget(self.audio_panel)
        self.window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.audio_dock
        )
        self.window.splitDockWidget(
            self.config_dock, self.audio_dock, Qt.Orientation.Vertical
        )
        view_menu.addAction(self.audio_dock.toggleViewAction())
        self.normalization.currentTextChanged.connect(self.audio_settings_changed)
        self.audio_codec.currentIndexChanged.connect(self.audio_settings_changed)
        self.audio_settings_changed()

    def build_output_settings(self, view_menu):
        self.output_panel = QWidget()
        form = QFormLayout(self.output_panel)
        self.project_name = QLineEdit(self.settings.value("output/project", ""))
        self.filename_format = QLineEdit(
            self.settings.value("output/format", "{project}.Assembly.{date}.mp4")
        )
        self.filename_format.setToolTip(
            "{project}: project name; {date}: YYYY-MM-DD. _A, _B, _C and _FINAL are added automatically."
        )
        self.output_folder = QLineEdit(self.settings.value("output/folder", ""))
        self.output_browse = QPushButton("Browse…")
        self.output_browse.clicked.connect(self.browse_output_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.output_folder, 1)
        folder_row.addWidget(self.output_browse)
        form.addRow("Project", self.project_name)
        form.addRow("Name format", self.filename_format)
        form.addRow("Output folder", folder_row)
        for label, widget, key in (
            ("Project", self.project_name, "project"),
            ("Name format", self.filename_format, "format"),
            ("Output folder", self.output_folder, "folder"),
        ):
            widget.setAccessibleName(label)
            widget.textChanged.connect(
                lambda text, key=key: self.settings.setValue(f"output/{key}", text)
            )
        self.output_dock = QDockWidget("Output Settings", self.window)
        self.output_dock.setObjectName("outputSettings")
        self.output_dock.setWidget(self.output_panel)
        self.window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.output_dock
        )
        self.window.splitDockWidget(
            self.audio_dock, self.output_dock, Qt.Orientation.Vertical
        )
        view_menu.addAction(self.output_dock.toggleViewAction())

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self.window, "Select output folder", self.output_folder.text()
        )
        if folder:
            self.output_folder.setText(folder)

    def audio_settings_changed(self):
        mode = self.normalization.currentText()
        self.settings.setValue("audio/normalization", mode)
        self.settings.setValue("audio/codec", self.audio_codec.currentData())

    def render_config(self):
        width, height = self.resolution.currentData()
        return RenderConfig(
            width,
            height,
            self.frame_rate.currentData(),
            self.encoder.currentData(),
            self.speed.currentData(),
            self.quality.value(),
            self.normalization.currentText(),
            self.audio_codec.currentData(),
        )

    def render_settings_changed(self):
        self.settings.setValue(
            "render/config", json.dumps(asdict(self.render_config()))
        )
        self.settings.setValue("render/combine", self.combine.isChecked())
        self.refresh()

    def apply_appearance(self):
        app = QApplication.instance()
        app.setStyleSheet("")
        theme = self.theme.currentData()
        if theme:
            qt_themes.set_theme(qt_themes.get_themes()[theme])
        else:
            qt_themes.set_theme(None, style=self.native_style)
        button = QPushButton()
        normal_height = button.sizeHint().height()
        frame = 2 * button.style().pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth)
        font_size = app.font().pointSizeF()
        button.deleteLater()
        app.setStyleSheet(
            Template(
                Path(__file__)
                .with_name("styles")
                .joinpath("components.qss")
                .read_text()
            ).substitute(
                medium_font_size=font_size * 1.25,
                medium_height=round(normal_height * 1.5) - frame,
                large_font_size=font_size * 1.5,
                large_height=normal_height * 2 - frame,
                xlarge_font_size=font_size * 2.5,
                xlarge_height=normal_height * 3 - frame,
            )
        )
        icon = QIcon(
            str(Path(__file__).with_name("icons") / f"{self.icon.currentData()}.ico")
        )
        app.setWindowIcon(icon)
        self.window.setWindowIcon(icon)
        self.settings.setValue("appearance/theme", theme)
        self.settings.setValue("appearance/icon", self.icon.currentData())
        self.refresh()

    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self.window, "Select video folder", self.settings.value("folder_path", "")
        )
        if folder:
            self.settings.setValue("folder_path", folder)
            self.add_paths([folder])

    def add_paths(self, paths):
        if paths and not self.clips:
            source = Path(paths[0]).resolve()
            self.project_name.setText(
                source.name if source.is_dir() else source.parent.name
            )
        known = {clip.path for clip in self.clips}
        self.pending = [path for path in video_paths(paths) if path not in known]
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.loading = True
        self.update_enabled()
        self.probe_next()

    def probe_next(self):
        if not self.pending:
            self.loading = False
            self.rebalance()
            return
        self.probing_path = self.pending.pop(0)
        self.progress.setRange(0, 0)
        self.window.statusBar().showMessage(f"Reading {self.probing_path.name}")
        self.probe.start(
            self.ffprobe,
            [
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(self.probing_path),
            ],
        )

    def probed(self, exit_code, exit_status):
        self.log.appendPlainText(bytes(self.probe.readAllStandardError()).decode())
        self.clips.append(
            clip_from_probe(
                self.probing_path, json.loads(bytes(self.probe.readAllStandardOutput()))
            )
        )
        self.progress.setRange(0, 1000)
        self.progress.setValue(1000)
        self.probe_next()

    def clear(self):
        self.selected_clip = None
        self.clips.clear()
        self.tracks = [[], [], []]
        self.refresh()

    def rebalance(self, longest_first=False):
        self.tracks = balance(self.clips, longest_first=longest_first)
        self.refresh()
        self.window.statusBar().showMessage("Ready")

    def refresh(self):
        config = self.render_config()
        for index, label in enumerate(self.column_headers):
            label.setText(
                f"{index + 1} · {COLUMN_NAMES[index]}\n⅓ of output · {config.column_width} × {config.height}"
            )
        self.export_button.setText(
            "Render columns + final video"
            if self.combine.isChecked()
            else "Render three column videos"
        )
        self.library.blockSignals(True)
        self.library.clear()
        for clip in self.clips:
            eligibility = "Portrait" if clip.portrait else "Excluded: not portrait"
            item = QListWidgetItem(
                f"{clip.path.name}\n{timestamp(clip.duration)} · {eligibility}"
            )
            item.setToolTip(str(clip.path))
            item.setData(Qt.ItemDataRole.UserRole, clip)
            self.library.addItem(item)
        self.library.blockSignals(False)
        eligible = sum(clip.portrait for clip in self.clips)
        self.library_summary.setText(
            f"{len(self.clips)} videos · {eligible} portrait · "
            f"{len(self.clips) - eligible} excluded"
        )
        durations = [
            sum(clip_duration(clip, config) for clip in track) for track in self.tracks
        ]
        self.timeline.clear()
        self.segment_bars = []
        palette = QApplication.palette()
        self.timeline.setBackground(palette.base().color())
        self.timeline.setLabel(
            "bottom", "Time", units="s", color=palette.text().color().name()
        )
        for axis in ("left", "bottom"):
            self.timeline.getAxis(axis).setTextPen(palette.text().color())
            self.timeline.getAxis(axis).setPen(palette.text().color())
        for column, (track, listing) in enumerate(zip(self.tracks, self.lists)):
            listing.blockSignals(True)
            listing.clear()
            start = 0
            for number, clip in enumerate(track):
                duration = clip_duration(clip, config)
                item = QListWidgetItem(
                    f"{number + 1}. {clip.path.name}\n"
                    f"{timestamp(start)} → {timestamp(start + duration)} "
                    f"· {timestamp(duration)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, clip)
                item.setToolTip(str(clip.path))
                listing.addItem(item)
                brush = palette.highlight().color()
                brush.setAlpha(190 if number % 2 == 0 else 110)
                bar = pg.BarGraphItem(
                    x0=start,
                    width=duration,
                    y=2 - column,
                    height=0.65,
                    brush=brush,
                    pen=palette.text().color(),
                )
                bar.setToolTip(f"{clip.path.name} · {timestamp(duration)}")
                self.timeline.addItem(bar)
                self.segment_bars.append((clip, bar))
                label = pg.TextItem(
                    str(number + 1),
                    color=palette.text().color(),
                    fill=palette.base().color(),
                    anchor=(0.5, 0.5),
                )
                label.setPos(start + duration / 2, 2 - column)
                self.timeline.addItem(label)
                start += duration
            listing.blockSignals(False)
            self.track_labels[column].setText(
                f"{COLUMN_NAMES[column]} · {len(track)} clips · {timestamp(durations[column])}"
            )
        self.timeline.setYRange(-0.6, 2.6, padding=0)
        self.timeline.setXRange(0, max(1, max(durations)), padding=0.02)
        self.summary.setText(f"Output Length: {timestamp(max(durations))}")
        self.select_clip(self.selected_clip)

    def select_source(self, row):
        if row >= 0:
            self.select_clip(self.library.item(row).data(Qt.ItemDataRole.UserRole))

    def select_column(self, column, row):
        if row >= 0:
            self.select_clip(self.tracks[column][row])

    def select_clip(self, clip):
        self.selected_clip = clip
        for listing in [self.library, *self.lists]:
            listing.blockSignals(True)
            row = next(
                (
                    index
                    for index in range(listing.count())
                    if listing.item(index).data(Qt.ItemDataRole.UserRole) == clip
                ),
                -1,
            )
            listing.setCurrentRow(row)
            if row >= 0:
                listing.scrollToItem(listing.item(row))
            listing.blockSignals(False)
        for column, listing in enumerate(self.lists):
            if listing.currentRow() >= 0:
                self.active_column = column
        for source, bar in self.segment_bars:
            bar.setOpts(
                pen=pg.mkPen(
                    QApplication.palette().text().color(),
                    width=3 if source == clip else 1,
                )
            )
        self.preview.set_clip(clip)
        self.update_enabled()

    def remove_selected_clip(self):
        path = self.selected_clip.path
        self.clips = [clip for clip in self.clips if clip.path != path]
        self.tracks = [
            [clip for clip in track if clip.path != path] for track in self.tracks
        ]
        self.selected_clip = None
        self.refresh()

    def reorder(self, offset):
        column = self.active_column
        row = self.lists[column].currentRow()
        track = self.tracks[column]
        track[row], track[row + offset] = track[row + offset], track[row]
        self.refresh()
        self.lists[column].setCurrentRow(row + offset)

    def move_column(self, offset):
        column = self.active_column
        row = self.lists[column].currentRow()
        clip = self.tracks[column].pop(row)
        target = column + offset
        self.tracks[target].append(clip)
        self.refresh()
        self.lists[target].setCurrentRow(len(self.tracks[target]) - 1)

    def timeline_clicked(self, event):
        if self.running or self.loading:
            return
        point = self.timeline.getViewBox().mapSceneToView(event.scenePos())
        column = 2 - round(point.y())
        if column in range(3) and abs(point.y() - (2 - column)) <= 0.325:
            config = self.render_config()
            start = 0
            for row, clip in enumerate(self.tracks[column]):
                duration = clip_duration(clip, config)
                if start <= point.x() < start + duration:
                    self.lists[column].setCurrentRow(row)
                    break
                start += duration

    def open_source(self, item):
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(item.data(Qt.ItemDataRole.UserRole).path))
        )

    def update_enabled(self):
        idle = not self.loading and not self.running
        for widget in (self.open_button, self.open_action, self.clear_action):
            widget.setEnabled(idle)
        self.balance_button.setEnabled(idle and bool(self.clips))
        self.longest_button.setEnabled(idle and bool(self.clips))
        self.export_button.setEnabled(idle and all(self.tracks))
        self.stop_button.setEnabled(self.running)
        self.render_panel.setEnabled(idle)
        self.audio_panel.setEnabled(idle)
        self.output_panel.setEnabled(idle)
        self.library.setEnabled(idle)
        self.remove_button.setEnabled(idle and self.selected_clip is not None)
        for listing in self.lists:
            listing.setEnabled(idle)
        column = self.active_column
        row = self.lists[column].currentRow()
        selected = idle and row >= 0
        self.up_button.setEnabled(selected and row > 0)
        self.down_button.setEnabled(selected and row < len(self.tracks[column]) - 1)
        self.left_button.setEnabled(selected and column > 0)
        self.right_button.setEnabled(selected and column < 2)

    def choose_export(self):
        if not self.output_folder.text().strip():
            self.window.statusBar().showMessage(
                "Export stopped: select an output folder in Output Settings."
            )
            return
        filename = self.filename_format.text().format(
            project=self.project_name.text(), date=date.today().isoformat()
        )
        self.start_export(Path(self.output_folder.text()) / filename)

    def start_export(self, output):
        columns = [
            output.with_name(f"{output.stem}_{name}.mp4") for name in ("A", "B", "C")
        ]
        output = output.with_name(f"{output.stem}_FINAL.mp4")
        targets = columns + ([output] if self.combine.isChecked() else [])
        existing = [path for path in targets if path.exists()]
        if existing:
            QMessageBox.critical(
                self.window,
                "Output files already exist",
                "Rendering was not started. Move or delete these files, or choose a different output name:\n\n"
                + "\n".join(str(path) for path in existing),
            )
            return
        self.output = output
        self.export_directory = tempfile.TemporaryDirectory(prefix="fastvideoassembly-")
        graph_root = Path(self.export_directory.name)
        config = self.render_config()
        self.export_jobs = []
        self.measurement_keys = {}
        self.audio_peaks = {}
        durations = [
            sum(clip_duration(clip, config) for clip in track) for track in self.tracks
        ]
        scheduled_measurements = set()
        self.column_cleanup = {}
        for index, (track, path) in enumerate(zip(self.tracks, columns)):
            manifest = graph_root / f"column{index}.ffconcat"
            jobs = list(column_jobs(track, path, manifest, config, self.audio_peaks))
            temporary_paths = [manifest]
            for clip, job in zip(track, jobs[:-1]):
                if (
                    config.normalization == "True Peak"
                    and clip.has_audio
                    and clip.path not in scheduled_measurements
                ):
                    self.measurement_keys[len(self.export_jobs)] = clip.path
                    self.export_jobs.append(
                        (clip.path, clip.duration, peak_measurement_arguments(clip))
                    )
                    scheduled_measurements.add(clip.path)
                self.export_jobs.append(job)
                temporary_paths.extend([job[0], job[0].with_suffix(".ffgraph")])
            self.column_cleanup[len(self.export_jobs)] = temporary_paths
            self.export_jobs.append(jobs[-1])
        if self.combine.isChecked():
            if config.normalization == "True Peak":
                self.measurement_keys[len(self.export_jobs)] = output
                self.export_jobs.append(
                    (
                        output,
                        max(durations),
                        mix_peak_arguments(columns, max(durations)),
                    )
                )
            args = partial(
                composition_arguments,
                columns,
                max(durations),
                output,
                graph_root / "composition.ffgraph",
                config,
            )
            self.export_jobs.append((output, max(durations), args))
        self.export_index = 0
        self.stop_requested = False
        self.progress_buffer = ""
        self.progress.setValue(0)
        self.log.clear()
        self.log_dock.show()
        self.running = True
        self.update_enabled()
        self.start_export_job()

    def start_export_job(self):
        self.progress.setValue(0)
        path, self.stage_duration, args = self.export_jobs[self.export_index]
        measuring = self.export_index in self.measurement_keys
        if callable(args):
            if (
                args.func is composition_arguments
                and self.render_config().normalization == "True Peak"
            ):
                args = args(peak=self.audio_peaks[path])
            else:
                args = args()
        self.progress_buffer = ""
        self.stage_log = ""
        operation = "Measuring audio" if measuring else "Rendering"
        self.window.statusBar().showMessage(
            f"{operation} {self.export_index + 1}/{len(self.export_jobs)} · {path.name}"
        )
        self.log.appendPlainText(f"{operation} {path}\n")
        self.process.start(self.ffmpeg, args)

    def stop_export(self):
        self.stop_requested = True
        self.process.write(b"q\n")

    def read_progress(self):
        self.progress_buffer += bytes(self.process.readAllStandardOutput()).decode()
        while "\n" in self.progress_buffer:
            line, self.progress_buffer = self.progress_buffer.split("\n", 1)
            if line.startswith("out_time_us=") and line[12:] != "N/A":
                seconds = int(line[12:]) / 1_000_000
                self.progress.setValue(
                    round(max(0, min(1, seconds / self.stage_duration)) * 1000)
                )

    def read_log(self):
        text = bytes(self.process.readAllStandardError()).decode()
        self.stage_log += text
        self.log.appendPlainText(text)

    def finished(self, exit_code, exit_status):
        self.read_progress()
        self.read_log()
        if exit_code == 0 and not self.stop_requested:
            self.progress.setValue(1000)
        self.log.appendPlainText(f"FFmpeg exited with code {exit_code}")
        if (
            exit_code == 0
            and not self.stop_requested
            and self.export_index in self.measurement_keys
        ):
            measured = json.loads(
                self.stage_log[
                    self.stage_log.rindex("{") : self.stage_log.rindex("}") + 1
                ]
            )
            self.audio_peaks[self.measurement_keys[self.export_index]] = float(
                measured["input_tp"]
            )
        if (
            exit_code == 0
            and not self.stop_requested
            and self.export_index in self.column_cleanup
        ):
            for path in self.column_cleanup[self.export_index]:
                path.unlink()
        if (
            exit_code == 0
            and not self.stop_requested
            and self.export_index + 1 < len(self.export_jobs)
        ):
            self.export_index += 1
            self.start_export_job()
            return
        self.running = False
        self.export_directory.cleanup()
        self.export_directory = None
        self.window.statusBar().showMessage(
            f"FFmpeg exited with code {exit_code} · {self.export_jobs[self.export_index][0]}"
        )
        self.update_enabled()

    def install_explorer(self):
        integrations.install(self.launcher_module)
        self.window.statusBar().showMessage(
            "Installed FastVideoAssembly in File Explorer"
        )

    def eventFilter(self, watched, event):
        if (
            event.type() in (QEvent.Type.DragEnter, QEvent.Type.Drop)
            and not self.loading
            and not self.running
            and event.mimeData().hasUrls()
        ):
            event.acceptProposedAction()
            if event.type() == QEvent.Type.Drop:
                self.add_paths([url.toLocalFile() for url in event.mimeData().urls()])
            return True
        if event.type() == QEvent.Type.Close:
            if self.running or self.loading:
                event.ignore()
                return True
            self.preview.player.stop()
            self.settings.setValue("mainWindow/geometry", self.window.saveGeometry())
            self.settings.setValue("mainWindow/state", self.window.saveState(1))
            self.settings.setValue(
                "mainWindow/splitterState", self.splitter.saveState()
            )
            self.settings.sync()
        return super().eventFilter(watched, event)


def main():
    if sys.argv[1:] == ["--install-explorer"]:
        return integrations.install()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    controller = Application(paths=sys.argv[1:])
    controller.window.show()
    return app.exec()
