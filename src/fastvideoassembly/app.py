"""Native Qt shell following FastVideoCropper's widget and appearance patterns."""

import json
import random
import sys
import tempfile
from dataclasses import asdict
from datetime import date
from functools import partial
from pathlib import Path
from string import Template
from time import monotonic

import pyqtgraph as pg
import qt_themes
from platformdirs import user_config_path
from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QObject,
    QProcess,
    QSettings,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFormLayout,
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
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import APP_NAME, APP_VERSION, integrations
from .assembly import (
    Clip,
    RenderConfig,
    Source,
    clip_duration,
    clip_from_probe,
    column_arguments,
    composition_arguments,
    timeline_name,
    video_paths,
)
from .audio import mix_peak_arguments, peak_measurement_arguments
from .hardware import render_hardware
from .preview import Preview
from .styles.timeline import TimelineClipStyle, TimelineTrackStyle
from .three_column import ThreeColumnAssembly, TimelineSegment
from .timeline import CLIP_HEIGHT, CLIP_Y_OFFSET, TRACK_HEIGHT, clip_spans, move_clips
from .updates import UpdateDialog


def timestamp(seconds):
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class VideoSourceDialog(QFileDialog):
    def __init__(self, parent, directory):
        super().__init__(parent, "Add Videos", directory)
        self.setOption(QFileDialog.Option.DontUseNativeDialog)
        self.setFileMode(QFileDialog.FileMode.ExistingFiles)
        self.setNameFilter("Videos (*.mp4 *.mkv *.mov *.avi *.webm)")
        self.setLabelText(QFileDialog.DialogLabel.Accept, "Add")

    def accept(self):
        QDialog.accept(self)


class Application(QObject):
    def __init__(
        self,
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        paths=(),
        launcher_module=integrations.APP_MODULE,
        no_profile=False,
    ):
        super().__init__()
        self.native_style = QApplication.style().objectName()
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.launcher_module = launcher_module
        if no_profile:
            self.settings_directory = tempfile.TemporaryDirectory(prefix="FastVideoAssembly-")
            settings_path = Path(self.settings_directory.name) / "settings.ini"
        else:
            settings_path = user_config_path(APP_NAME, appauthor=False) / "settings.ini"
        self.settings = QSettings(
            str(settings_path),
            QSettings.Format.IniFormat,
        )
        if no_profile:
            self.settings.setFallbacksEnabled(False)
        self.clips = []
        self.pending = []
        self.loading = False
        self.running = False
        self.scanning_paused = False
        self.scan_stop_requested = False
        self.render_paused = False
        self.render_waiting = False
        self.selected_clip = None
        self.export_directory = None
        self.window = QMainWindow()
        self.window.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.window.resize(1280, 850)
        self.window.setAcceptDrops(True)
        self.window.installEventFilter(self)
        self.probe = QProcess(self)
        self.probe.finished.connect(partial(self.probed, self.probe))
        self.probes = [self.probe]
        self.probing_paths = {}
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_progress)
        self.process.readyReadStandardError.connect(self.read_log)
        self.process.finished.connect(self.finished)
        self.measurement_processes = {}
        self.replace_outputs = set()
        self.runtime_timer = QTimer(self.window)
        self.runtime_timer.setInterval(1000)
        self.runtime_timer.timeout.connect(self.update_runtime)
        self.build_ui()
        self.apply_appearance()
        if self.settings.contains("mainWindow/geometry"):
            self.window.restoreGeometry(self.settings.value("mainWindow/geometry"))
        if self.settings.contains("mainWindow/state"):
            self.window.restoreState(self.settings.value("mainWindow/state"), 1)
        saved_sources = self.settings.value("sources/paths", [], type=list)
        scanned = {}
        for index in range(self.settings.beginReadArray("sources/scanned")):
            self.settings.setArrayIndex(index)
            path = Path(self.settings.value("path"))
            scanned[path] = Clip(
                path,
                self.settings.value("duration", type=float),
                self.settings.value("width", type=float),
                self.settings.value("height", type=float),
                self.settings.value("has_audio", type=bool),
            )
        self.settings.endArray()
        self.clips = [
            scanned[Path(path)] if Path(path) in scanned else Source(Path(path))
            for path in saved_sources
        ]
        for index in range(self.settings.beginReadArray("assembly/timelines")):
            self.settings.setArrayIndex(index)
            self.assembler.tracks[index] = [
                scanned[Path(path)]
                for path in self.settings.value("paths", type=list)
            ]
        self.settings.endArray()
        self.refresh()
        if paths:
            self.add_paths(paths, initialize_project=not saved_sources)

    def build_ui(self):
        file_menu = self.window.menuBar().addMenu("&File")
        self.open_action = QAction("&Add Videos...", self)
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
        apply = QPushButton("Apply")
        apply.clicked.connect(self.apply_appearance)
        appearance_layout.addWidget(apply)
        appearance_action = QWidgetAction(self.window)
        appearance_action.setDefaultWidget(appearance_widget)
        appearance.addAction(appearance_action)
        help_menu = self.window.menuBar().addMenu("&Help")
        self.update_action = help_menu.addAction("Check for Updates...", self.check_updates)
        help_menu.addAction("Install in File Explorer", self.install_explorer)

        library_widget = QWidget()
        library_layout = QVBoxLayout(library_widget)
        self.open_button = QPushButton("Add Videos")
        self.open_button.clicked.connect(self.open_folder)
        library_layout.addWidget(self.open_button)
        self.library = QListWidget()
        self.library.setAccessibleName("Source videos")
        self.library.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.library.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.library.setAcceptDrops(True)
        self.library.viewport().setAcceptDrops(True)
        self.library.viewport().installEventFilter(self)
        self.library.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.library.currentRowChanged.connect(self.select_source)
        self.library.itemSelectionChanged.connect(self.select_source)
        library_layout.addWidget(self.library)
        self.remove_sources_button = QPushButton("Remove selected")
        self.remove_sources_button.clicked.connect(self.remove_selected_clip)
        library_layout.addWidget(self.remove_sources_button)
        self.clear_sources_button = QPushButton("Clear all")
        self.clear_sources_button.clicked.connect(self.clear)
        library_layout.addWidget(self.clear_sources_button)
        scan_row = QHBoxLayout()
        self.parallel_scanning = QCheckBox("Source scanning threads")
        self.parallel_scanning.setChecked(
            self.settings.value("sources/parallel_scanning", True, type=bool)
        )
        self.scan_threads = QSpinBox()
        self.scan_threads.setRange(1, 2147483647)
        self.scan_threads.setValue(
            self.settings.value("sources/scan_threads", 2, type=int)
        )
        self.scan_threads.setAccessibleName("Source scanning threads")
        self.scan_threads.setToolTip(
            "Number of concurrent FFprobe workers used when creating timelines."
        )
        self.parallel_scanning.toggled.connect(
            lambda enabled: self.settings.setValue("sources/parallel_scanning", enabled)
        )
        self.scan_threads.valueChanged.connect(
            lambda count: self.settings.setValue("sources/scan_threads", count)
        )
        scan_row.addWidget(self.parallel_scanning)
        scan_row.addWidget(self.scan_threads)
        library_layout.addLayout(scan_row)
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

        self.assembler_tabs = QTabWidget()
        self.assembler = ThreeColumnAssembly(self)
        self.assembler_tabs.addTab(self.assembler, "Column Assembly")
        self.window.setCentralWidget(self.assembler_tabs)
        process_panel = QWidget()
        process_layout = QVBoxLayout(process_panel)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        process_layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log_dock = QDockWidget("Activity", self.window)
        self.log_dock.setObjectName("processLog")
        process_layout.addWidget(self.log, 1)
        log_actions = QHBoxLayout()
        self.copy_output = QPushButton("Copy output")
        self.copy_output.clicked.connect(self.copy_log)
        self.clear_output = QPushButton("Clear output")
        self.clear_output.clicked.connect(self.log.clear)
        log_actions.addWidget(self.copy_output)
        log_actions.addWidget(self.clear_output)
        log_actions.addStretch()
        process_layout.addLayout(log_actions)
        self.log_dock.setWidget(process_panel)
        self.window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()
        view_menu.addAction(self.log_dock.toggleViewAction())

    def copy_log(self):
        self.log.selectAll()
        self.log.copy()

    def build_render_settings(self, view_menu):
        self.render_panel = QWidget()
        form = QFormLayout(self.render_panel)
        self.resolution = QComboBox()
        self.resolution.addItem("1920 x 1080", [1920, 1080])
        self.resolution.addItem("3840 x 2160", [3840, 2160])
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
        self.encoder.addItem("NVIDIA HEVC - 10-bit", "hevc_nvenc")
        self.encoder.addItem("NVIDIA H.264 - 8-bit", "h264_nvenc")
        self.encoder.addItem("CPU H.264 - 8-bit", "libx264")
        self.speed = QComboBox()
        for label, value in (
            ("Fastest", "fastest"),
            ("Faster", "fast"),
            ("Fast", "fast_medium"),
            ("Balanced", "balanced"),
            ("Slow", "slow"),
            ("Slower", "quality"),
            ("Slowest", "slowest"),
        ):
            self.speed.addItem(label, value)
        self.quality = QSpinBox()
        self.quality.setRange(1, 51)
        decoders, scalers = render_hardware(self.ffmpeg)
        self.decoder = QComboBox()
        for label, value in decoders:
            self.decoder.addItem(label, value)
        self.decoder.setToolTip("Supported source codecs depend on the selected GPU.")
        self.scaler = QComboBox()
        for label, value in scalers:
            self.scaler.addItem(label, value)
        self.scaling_algorithm = QComboBox()
        for value in ("nearest", "bilinear", "bicubic", "lanczos"):
            self.scaling_algorithm.addItem(value.title(), value)
        self.qsv_scaling_mode = QComboBox()
        self.qsv_scaling_mode.addItem("Low Power", "low_power")
        self.qsv_scaling_mode.addItem("High Quality", "hq")
        self.combine = QCheckBox("Create final assembly")
        self.settings.remove("render/config")
        saved = RenderConfig(**{
            key: self.settings.value(f"render/{key}", value, type=type(value))
            for key, value in asdict(RenderConfig()).items()
        })
        self.resolution.setCurrentIndex(
            self.resolution.findData([saved.column_width * self.settings.value("assembly/columns", 3, type=int), saved.height])
        )
        self.frame_rate.setCurrentIndex(self.frame_rate.findData(saved.fps))
        self.encoder.setCurrentIndex(self.encoder.findData(saved.encoder))
        self.speed.setCurrentIndex(self.speed.findData(saved.speed))
        self.quality.setValue(saved.quality)
        for combo, value, labels in (
            (self.decoder, saved.decoder, {
                "none": "CPU", "cuda": "NVIDIA NVDEC", "qsv": "Intel Quick Sync",
                "d3d11va": "Windows D3D11", "dxva2": "Windows DXVA2",
            }),
            (self.scaler, saved.scaler, {
                "cpu": "CPU", "cuda": "NVIDIA CUDA", "qsv": "Intel Quick Sync",
            }),
        ):
            if combo.findData(value) == -1:
                combo.addItem(f"{labels[value]} (unavailable)", value)
                combo.model().item(combo.count() - 1).setEnabled(False)
        self.decoder.setCurrentIndex(self.decoder.findData(saved.decoder))
        self.scaler.setCurrentIndex(self.scaler.findData(saved.scaler))
        self.scaling_algorithm.setCurrentIndex(self.scaling_algorithm.findData(saved.scaling_algorithm))
        self.qsv_scaling_mode.setCurrentIndex(self.qsv_scaling_mode.findData(saved.qsv_scaling_mode))
        self.scaling_algorithm.setEnabled(saved.scaler in ("cpu", "cuda"))
        self.qsv_scaling_mode.setEnabled(saved.scaler == "qsv")
        self.filter_threads = QSpinBox()
        self.filter_threads.setRange(1, 256)
        self.filter_threads.setValue(saved.filter_threads)
        self.applied_filter_threads = saved.filter_threads
        self.filter_threads.setToolTip("CPU threads for video and audio filter graphs per render job.")
        self.combine.setChecked(self.settings.value("render/combine", True, type=bool))
        for title, widget in [
            ("Output size", self.resolution),
            ("Frames / second", self.frame_rate),
            ("Encoder", self.encoder),
            ("Speed / quality", self.speed),
            ("Quality value", self.quality),
            ("Video decoding", self.decoder),
            ("Video scaling", self.scaler),
            ("Scaling interpolation", self.scaling_algorithm),
            ("Quick Sync scaling", self.qsv_scaling_mode),
        ]:
            form.addRow(title, widget)
            widget.setAccessibleName(title)
        self.filter_threads.setAccessibleName("CPU filter threads")
        filter_threads_row = QHBoxLayout()
        filter_threads_row.addWidget(self.filter_threads)
        self.apply_filter_threads_button = QPushButton("Apply")
        self.apply_filter_threads_button.clicked.connect(self.apply_filter_threads)
        filter_threads_row.addWidget(self.apply_filter_threads_button)
        self.reset_filter_threads_button = QPushButton("Reset")
        self.reset_filter_threads_button.clicked.connect(
            lambda: self.filter_threads.setValue(self.applied_filter_threads)
        )
        filter_threads_row.addWidget(self.reset_filter_threads_button)
        form.addRow("CPU filter threads", filter_threads_row)
        self.config_dock = QDockWidget("Render Settings", self.window)
        self.config_dock.setObjectName("sharedRenderConfiguration")
        self.config_dock.setWidget(self.render_panel)
        self.window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.config_dock
        )
        view_menu.addAction(self.config_dock.toggleViewAction())
        for combo in (self.resolution, self.frame_rate, self.encoder, self.speed,
                      self.decoder, self.scaler, self.scaling_algorithm, self.qsv_scaling_mode):
            combo.currentIndexChanged.connect(self.render_settings_changed)
        self.quality.valueChanged.connect(self.render_settings_changed)
        self.combine.toggled.connect(
            lambda checked: self.settings.setValue("render/combine", checked)
        )

    def build_audio_settings(self, view_menu):
        self.audio_panel = QWidget()
        layout = QVBoxLayout(self.audio_panel)
        codec_form = QFormLayout()
        self.audio_codec = QComboBox()
        for label, value in (
            ("No Audio", "none"),
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
        self.normalization = QComboBox()
        self.normalization.addItems(["None", "True Peak", "YouTube"])
        self.normalization.setAccessibleName("Normalization mode")
        self.normalization.setCurrentText(
            self.settings.value("audio/normalization", "None")
        )
        codec_form.addRow("Normalize Audio", self.normalization)
        self.analysis_workers = QSpinBox()
        self.analysis_workers.setRange(1, 32)
        self.analysis_workers.setValue(self.settings.value("audio/analysis_workers", 2, type=int))
        self.analysis_workers.setAccessibleName("Audio analysis workers")
        self.analysis_workers.setToolTip("Maximum simultaneous True Peak measurements before each column render.")
        codec_form.addRow("Audio analysis workers", self.analysis_workers)
        layout.addLayout(codec_form)
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
        self.analysis_workers.valueChanged.connect(self.audio_settings_changed)
        self.audio_settings_changed()

    def build_output_settings(self, view_menu):
        self.output_panel = QWidget()
        form = QFormLayout(self.output_panel)
        self.project_name = QLineEdit(self.settings.value("output/project", ""))
        self.project_from_folder = QCheckBox("Enable")
        self.project_from_folder.setAccessibleName("Enable project from folder")
        self.project_from_folder.setChecked(
            self.settings.value("output/project_from_folder", False, type=bool)
        )
        self.project_folder_level = QSpinBox()
        self.project_folder_level.setRange(-2147483648, 0)
        self.project_folder_level.setValue(
            self.settings.value("output/project_folder_level", 0, type=int)
        )
        self.project_folder_level.setAccessibleName("Project from folder")
        self.project_folder_level.setToolTip(
            "0: first source's parent folder; -1: one folder up; -2: two folders up."
        )
        project_folder_row = QHBoxLayout()
        project_folder_row.addWidget(self.project_from_folder)
        project_folder_row.addWidget(self.project_folder_level, 1)
        self.project_from_folder.toggled.connect(self.update_project_from_folder)
        self.project_folder_level.valueChanged.connect(self.update_project_from_folder)
        self.filename_format = QLineEdit(
            self.settings.value("output/format", "{project}.Assembly.{date}.mp4")
        )
        self.filename_format.setToolTip(
            "{project}: project name; {date}: YYYY-MM-DD. _A, _B, _C and _FINAL are added automatically."
        )
        self.output_folder = QLineEdit(self.settings.value("output/folder", ""))
        self.output_browse = QPushButton("Browse...")
        self.output_browse.clicked.connect(self.browse_output_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.output_folder, 1)
        folder_row.addWidget(self.output_browse)
        self.output_open = QPushButton("Open folder")
        self.output_open.setEnabled(bool(self.output_folder.text().strip()))
        self.output_folder.textChanged.connect(
            lambda text: self.output_open.setEnabled(bool(text.strip()))
        )
        self.output_open.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_folder.text()))
        )
        form.addRow("Project", self.project_name)
        form.addRow("Project from folder", project_folder_row)
        form.addRow("Name format", self.filename_format)
        form.addRow("Output folder", folder_row)
        form.addRow("", self.output_open)
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

    def update_project_from_folder(self):
        enabled = self.project_from_folder.isChecked()
        self.project_name.setReadOnly(enabled)
        if self.clips:
            parents = self.clips[0].path.parents
            self.project_folder_level.blockSignals(True)
            self.project_folder_level.setRange(1 - len(parents), 0)
            self.project_folder_level.blockSignals(False)
            if enabled:
                self.project_name.setText(parents[-self.project_folder_level.value()].name)
        self.settings.setValue("output/project_from_folder", enabled)
        self.settings.setValue("output/project_folder_level", self.project_folder_level.value())

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self.window, "Select output folder", self.output_folder.text()
        )
        if folder:
            self.output_folder.setText(folder)

    def audio_settings_changed(self):
        self.normalization.setEnabled(self.audio_codec.currentData() != "none")
        mode = self.normalization.currentText()
        self.analysis_workers.setEnabled(self.audio_codec.currentData() != "none" and mode == "True Peak")
        self.settings.setValue("audio/analysis_workers", self.analysis_workers.value())
        self.settings.setValue("audio/normalization", mode)
        self.settings.setValue("audio/codec", self.audio_codec.currentData())

    def render_config(self):
        width, height = self.resolution.currentData()
        return RenderConfig(
            width // self.assembler.columns.currentData(),
            height,
            self.frame_rate.currentData(),
            self.encoder.currentData(),
            self.speed.currentData(),
            self.quality.value(),
            self.normalization.currentText(),
            self.audio_codec.currentData(),
            self.applied_filter_threads,
            self.decoder.currentData(),
            self.scaler.currentData(),
            self.scaling_algorithm.currentData(),
            self.qsv_scaling_mode.currentData(),
        )

    def apply_filter_threads(self):
        self.applied_filter_threads = self.filter_threads.value()
        self.render_settings_changed()

    def render_settings_changed(self):
        self.scaling_algorithm.setEnabled(self.scaler.currentData() in ("cpu", "cuda"))
        self.qsv_scaling_mode.setEnabled(self.scaler.currentData() == "qsv")
        for key, value in asdict(self.render_config()).items():
            self.settings.setValue(f"render/{key}", value)
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
        dialog = VideoSourceDialog(
            self.window, self.settings.value("folder_path", "")
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings.setValue("folder_path", dialog.directory().absolutePath())
            self.add_paths(dialog.selectedFiles())
        dialog.deleteLater()

    def add_paths(self, paths, initialize_project=True):
        known = {clip.path for clip in self.clips}
        additions = [path for path in video_paths(paths) if path not in known]
        if (
            initialize_project and paths and not self.clips
            and not self.project_from_folder.isChecked()
        ):
            source = Path(paths[0]).resolve()
            self.project_name.setText(
                source.name if source.is_dir() else source.parent.name
            )
        if not additions:
            return
        self.clips.extend(Source(path) for path in additions)
        self.save_active_state()
        self.refresh()

    def save_active_state(self):
        self.settings.setValue("sources/paths", [str(clip.path) for clip in self.clips])
        scanned = [clip for clip in self.clips if isinstance(clip, Clip)]
        self.settings.remove("sources/scanned")
        self.settings.beginWriteArray("sources/scanned", len(scanned))
        for index, clip in enumerate(scanned):
            self.settings.setArrayIndex(index)
            self.settings.setValue("path", str(clip.path))
            self.settings.setValue("duration", clip.duration)
            self.settings.setValue("width", clip.width)
            self.settings.setValue("height", clip.height)
            self.settings.setValue("has_audio", clip.has_audio)
        self.settings.endArray()
        self.settings.remove("assembly/timelines")
        self.settings.beginWriteArray("assembly/timelines", len(self.assembler.tracks))
        for index, track in enumerate(self.assembler.tracks):
            self.settings.setArrayIndex(index)
            self.settings.setValue("paths", [str(clip.path) for clip in track])
        self.settings.endArray()
        self.settings.sync()

    def create_timelines(self):
        if not self.assembler.keep_logs.isChecked():
            self.log.clear()
        self.scanning_paused = False
        self.scan_stop_requested = False
        self.pending = [clip.path for clip in self.clips if isinstance(clip, Source)]
        if not self.pending:
            self.rebalance()
            return
        self.scan_started = monotonic()
        self.scan_completed = 0
        self.progress.setFormat("%v / %m videos scanned - 0.0 it/s")
        self.progress.setRange(0, len(self.clips))
        self.progress.setValue(len(self.clips) - len(self.pending))
        self.scan_worker_count = (
            self.scan_threads.value() if self.parallel_scanning.isChecked() else 1
        )
        for _ in range(len(self.probes), min(self.scan_worker_count, len(self.pending))):
            probe = QProcess(self)
            probe.finished.connect(partial(self.probed, probe))
            self.probes.append(probe)
        self.loading = True
        self.update_enabled()
        self.probe_next()

    def probe_next(self):
        if not self.pending and not self.probing_paths:
            self.loading = False
            self.scanning_paused = False
            self.scan_stop_requested = False
            self.rebalance()
            return
        if self.scan_stop_requested:
            if not self.probing_paths:
                self.loading = False
                self.scanning_paused = False
                self.scan_stop_requested = False
                self.window.statusBar().showMessage("Scanning stopped. Create Timelines to continue.")
                self.refresh()
            return
        if self.scanning_paused:
            if not self.probing_paths:
                self.scan_pause_started = monotonic()
                self.window.statusBar().showMessage("Scanning paused")
            return
        for probe in self.probes[:self.scan_worker_count]:
            if self.pending and probe not in self.probing_paths:
                path = self.pending.pop(0)
                self.probing_paths[probe] = path
                self.log_dock.show()
                self.window.statusBar().showMessage(
                    f"Scanning: {path.name}"
                )
                probe.start(
                    self.ffprobe,
                    [
                        "-v",
                        "error",
                        "-show_streams",
                        "-show_format",
                        "-of",
                        "json",
                        str(path),
                    ],
                )

    def pause_scanning(self):
        self.scanning_paused = not self.scanning_paused
        if not self.scanning_paused and not self.probing_paths:
            self.scan_started += monotonic() - self.scan_pause_started
        self.window.statusBar().showMessage(
            "Pausing scanning after active scans finish" if self.scanning_paused
            else "Resuming scanning"
        )
        self.update_enabled()
        self.probe_next()

    def stop_scanning(self):
        self.scan_stop_requested = True
        self.window.statusBar().showMessage("Stopping scanning after active scans finish")
        self.update_enabled()
        self.probe_next()

    def probed(self, probe, exit_code, exit_status):
        self.log.appendPlainText(bytes(probe.readAllStandardError()).decode())
        clip = clip_from_probe(
            self.probing_paths[probe], json.loads(bytes(probe.readAllStandardOutput()))
        )
        index = next(i for i, source in enumerate(self.clips) if source.path == clip.path)
        if self.selected_clip == self.clips[index]:
            self.selected_clip = clip
        self.clips[index] = clip
        self.save_active_state()
        self.progress.setValue(self.progress.value() + 1)
        self.scan_completed += 1
        rate = self.scan_completed / (monotonic() - self.scan_started)
        self.progress.setFormat(f"%v / %m videos scanned - {rate:.1f} it/s")
        del self.probing_paths[probe]
        self.probe_next()

    def clear(self):
        self.assembler.selected_timelines.clear()
        self.selected_clip = None
        self.clips.clear()
        self.assembler.tracks = [[] for _ in range(self.assembler.columns.currentData() * self.assembler.divisions.value())]
        self.save_active_state()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.window.statusBar().showMessage("Ready")
        self.refresh()

    def divisions_changed(self, value):
        self.assembler.selected_timelines.clear()
        self.settings.setValue("assembly/divisions", value)
        self.assembler.tracks = [[] for _ in range(self.assembler.columns.currentData() * value)]
        self.save_active_state()
        self.refresh()

    def columns_changed(self):
        self.assembler.selected_timelines.clear()
        self.settings.setValue("assembly/columns", self.assembler.columns.currentData())
        self.assembler.tracks = [[] for _ in range(self.assembler.columns.currentData() * self.assembler.divisions.value())]
        self.render_settings_changed()
        self.save_active_state()

    def clear_timeline_selection(self):
        self.assembler.selected_timelines.clear()
        for background in self.assembler.track_backgrounds:
            TimelineTrackStyle.apply(background, False)
        self.update_enabled()

    def finish_timeline_edit(self):
        self.save_active_state()
        view_range = self.assembler.timeline.getViewBox().viewRange()
        self.refresh()
        self.assembler.timeline.getViewBox().setRange(xRange=view_range[0], yRange=view_range[1], padding=0)

    @property
    def selected_clips(self):
        return {item.data(Qt.ItemDataRole.UserRole) for item in self.library.selectedItems()}

    @property
    def target_timelines(self):
        return self.assembler.selected_timelines or range(len(self.assembler.tracks))

    def sort_timelines(self, longest_first=False):
        for column in self.target_timelines:
            self.assembler.tracks[column].sort(key=lambda clip: clip.duration, reverse=longest_first)
        self.finish_timeline_edit()

    def shuffle_timelines(self):
        for column in self.target_timelines:
            random.shuffle(self.assembler.tracks[column])
        self.finish_timeline_edit()

    def rebalance(self, longest_first=False):
        self.assembler.rebalance(self.clips, longest_first=longest_first)
        self.save_active_state()
        self.refresh()
        self.window.statusBar().showMessage("Ready")

    def refresh(self):
        self.update_project_from_folder()
        selected_paths = {
            item.data(Qt.ItemDataRole.UserRole).path
            for item in self.library.selectedItems()
        }
        config = self.render_config()
        self.library.blockSignals(True)
        self.library.clear()
        for clip in self.clips:
            item = QListWidgetItem(clip.path.name)
            item.setToolTip(str(clip.path))
            item.setData(Qt.ItemDataRole.UserRole, clip)
            self.library.addItem(item)
        self.library.blockSignals(False)
        durations = [
            sum(clip_duration(clip, config) for clip in track)
            for track in self.assembler.tracks
        ]
        self.assembler.timeline.clear()
        self.assembler.segment_bars = []
        palette = QApplication.palette()
        self.assembler.timeline.setBackground(palette.base().color())
        self.assembler.timeline.setLabel(
            "bottom", "Time", units="s", color=palette.text().color().name()
        )
        for axis in ("left", "bottom"):
            self.assembler.timeline.getAxis(axis).setTextPen(palette.text().color())
            self.assembler.timeline.getAxis(axis).setPen(palette.text().color())
        self.assembler.division_offsets = []
        self.assembler.segment_bounds = []
        self.assembler.dividers = []
        self.assembler.track_labels = []
        self.assembler.track_backgrounds = []
        self.assembler.track_bounds = []
        offset = 0.0
        columns = self.assembler.columns.currentData()
        heading_height = TRACK_HEIGHT / 2 - (CLIP_Y_OFFSET + CLIP_HEIGHT / 2)
        self.assembler.timeline.setMinimumHeight(
            round(columns * (self.assembler.fontMetrics().height() + 8) / heading_height
                  + self.assembler.timeline.getAxis("bottom").height())
        )
        for group_start in range(0, len(self.assembler.tracks), columns):
            group_width = max(1, max(durations[group_start:group_start + columns]))
            self.assembler.division_offsets.append(offset)
            if group_start:
                divider = pg.InfiniteLine(offset, angle=90, pen=pg.mkPen(palette.text().color(), width=2))
                self.assembler.timeline.addItem(divider)
                self.assembler.dividers.append(divider)
            for column in range(group_start, group_start + columns):
                track = self.assembler.tracks[column]
                y = columns - 1 - column % columns
                background = pg.BarGraphItem(x0=offset, width=group_width, y=y, height=TRACK_HEIGHT)
                background.setZValue(-10)
                TimelineTrackStyle.apply(background, column in self.assembler.selected_timelines)
                self.assembler.timeline.addItem(background)
                self.assembler.track_backgrounds.append(background)
                self.assembler.track_bounds.append((column, offset, offset + group_width, y))
                heading = pg.TextItem(
                    f"{timeline_name(column)} - {len(track)} clips - {timestamp(durations[column])}",
                    color=palette.text().color(), anchor=(0, 0.5),
                )
                heading.textItem.document().setDocumentMargin(8)
                heading.setPos(offset, y + (CLIP_Y_OFFSET + CLIP_HEIGHT / 2 + TRACK_HEIGHT / 2) / 2)
                self.assembler.timeline.addItem(heading)
                self.assembler.track_labels.append(heading)
                for number, (clip_start, clip_end, clip) in enumerate(clip_spans(track, config)):
                    start = offset + clip_start
                    duration = clip_end - clip_start
                    bar = TimelineSegment(
                        self, column, number,
                        x0=start, width=duration, y=y + CLIP_Y_OFFSET, height=CLIP_HEIGHT,
                    )
                    bar.setToolTip(f"{timeline_name(column)} - {clip.path.name} - {timestamp(duration)}")
                    self.assembler.timeline.addItem(bar)
                    self.assembler.segment_bars.append((clip, bar))
                    self.assembler.segment_bounds.append((column, start, start + duration, clip))
                    label = pg.TextItem(str(number + 1), color=palette.text().color(),
                                        fill=palette.base().color(), anchor=(0.5, 0.5))
                    label.setParentItem(bar)
                    label.setPos(start + duration / 2, y + CLIP_Y_OFFSET)
            offset += group_width
        self.assembler.timeline.setYRange(-0.6, columns - 0.2, padding=0)
        self.assembler.timeline.setXRange(0, offset, padding=0.02)
        self.library.blockSignals(True)
        for row in range(self.library.count()):
            item = self.library.item(row)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole).path in selected_paths)
            if item.data(Qt.ItemDataRole.UserRole) == self.selected_clip:
                self.library.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.library.blockSignals(False)
        self.select_clip(self.selected_clip, sync_source=False)

    def select_source(self, row=None):
        items = self.library.selectedItems()
        current = self.library.currentItem()
        item = current if current in items else next(iter(items), None)
        self.select_clip(
            item.data(Qt.ItemDataRole.UserRole) if item is not None else None,
            sync_source=False,
        )

    def select_clip(self, clip, sync_source=True):
        self.selected_clip = clip
        listings = [self.library] if sync_source else []
        for listing in listings:
            listing.blockSignals(True)
            listing.clearSelection()
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
        selected = self.selected_clips
        for source, bar in self.assembler.segment_bars:
            TimelineClipStyle.apply(bar, source in selected)
        self.preview.set_clip(clip)
        self.update_enabled()

    def remove_selected_clip(self):
        paths = {
            item.data(Qt.ItemDataRole.UserRole).path
            for item in self.library.selectedItems()
        }
        self.clips = [clip for clip in self.clips if clip.path not in paths]
        self.assembler.tracks = [
            [clip for clip in track if clip.path not in paths]
            for track in self.assembler.tracks
        ]
        self.selected_clip = None
        self.finish_timeline_edit()

    def move_selected_clips(self, target):
        selected = self.selected_clips
        config = self.render_config()
        for track in self.assembler.tracks:
            track[:], _position = move_clips(track, selected, target, config)
        self.finish_timeline_edit()

    def timeline_clicked(self, event):
        if self.running or self.loading or event.isAccepted() or event.button() != Qt.MouseButton.LeftButton:
            return
        point = self.assembler.timeline.getViewBox().mapSceneToView(event.scenePos())
        columns = self.assembler.columns.currentData()
        row = columns - 1 - round(point.y())
        if row in range(columns) and abs(point.y() - (columns - 1 - row + CLIP_Y_OFFSET)) <= CLIP_HEIGHT / 2:
            for column, start, end, clip in self.assembler.segment_bounds:
                if column % columns == row and start <= point.x() < end:
                    item = next(self.library.item(i) for i in range(self.library.count())
                                if self.library.item(i).data(Qt.ItemDataRole.UserRole) == clip)
                    self.library.blockSignals(True)
                    selected = not item.isSelected()
                    self.library.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
                    item.setSelected(selected)
                    self.library.blockSignals(False)
                    self.select_source()
                    event.accept()
                    return
        for column, start, end, y in self.assembler.track_bounds:
            if start <= point.x() < end and abs(point.y() - y) <= TRACK_HEIGHT / 2:
                self.assembler.selected_timelines.symmetric_difference_update({column})
                TimelineTrackStyle.apply(self.assembler.track_backgrounds[column], column in self.assembler.selected_timelines)
                self.update_enabled()
                event.accept()
                return

    def update_enabled(self):
        idle = not self.loading and not self.running
        self.update_action.setEnabled(idle)
        for widget in (self.open_button, self.open_action, self.clear_action):
            widget.setEnabled(idle)
        scanned = bool(self.clips) and all(isinstance(clip, Clip) for clip in self.clips)
        selected_count = len(self.assembler.selected_timelines)
        self.assembler.timelines_group.setTitle(f"Timelines ({selected_count if selected_count else 'All'})")
        self.assembler.select_no_timelines_button.setEnabled(idle and selected_count > 0)
        self.assembler.balance_button.setEnabled(idle and scanned)
        self.assembler.longest_button.setEnabled(idle and scanned)
        self.assembler.shuffle_button.setEnabled(idle and scanned)
        self.assembler.create_button.setEnabled(idle and bool(self.clips))
        self.assembler.scan_pause_button.setEnabled(self.loading and not self.scan_stop_requested)
        self.assembler.scan_pause_button.setText("Resume" if self.scanning_paused else "Pause")
        self.assembler.scan_stop_button.setEnabled(self.loading and not self.scan_stop_requested)
        self.assembler.export_button.setEnabled(idle and all(self.assembler.tracks))
        self.assembler.pause_button.setEnabled(self.running)
        self.assembler.pause_button.setText("Resume" if self.render_paused else "Pause")
        self.assembler.stop_button.setEnabled(self.running)
        self.render_panel.setEnabled(idle)
        self.combine.setEnabled(idle)
        self.assembler.remove_timelines.setEnabled(idle and self.combine.isChecked())
        self.audio_panel.setEnabled(idle)
        self.output_panel.setEnabled(idle)
        self.library.setEnabled(idle)
        removable = idle and bool(self.library.selectedItems())
        self.assembler.remove_button.setEnabled(removable)
        self.assembler.select_none_button.setEnabled(removable)
        self.remove_sources_button.setEnabled(removable)
        self.clear_sources_button.setEnabled(idle and bool(self.clips))
        self.parallel_scanning.setEnabled(idle)
        self.scan_threads.setEnabled(idle)
        self.assembler.divisions.setEnabled(idle)
        self.assembler.columns.setEnabled(idle)
        selected = self.selected_clips
        count = sum(clip in selected for track in self.assembler.tracks for clip in track)
        self.assembler.clips_group.setTitle(f"Clips ({count})")
        earlier = idle and any(track[i] in selected and track[i - 1] not in selected
                               for track in self.assembler.tracks for i in range(1, len(track)))
        later = idle and any(track[i] in selected and track[i + 1] not in selected
                             for track in self.assembler.tracks for i in range(len(track) - 1))
        self.assembler.forward_button.setEnabled(later)
        self.assembler.start_button.setEnabled(earlier)
        self.assembler.backward_button.setEnabled(earlier)
        self.assembler.end_button.setEnabled(later)

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
        count = len(self.assembler.tracks)
        columns_per_division = self.assembler.columns.currentData()
        columns = [output.with_name(f"{output.stem}_{timeline_name(index)}.mp4") for index in range(count)]
        finals = [
            output.with_name(f"{output.stem}_FINAL{suffix}.mp4")
            for suffix in ([""] if count == columns_per_division else [
                "_" + "".join(timeline_name(index) for index in range(start, start + columns_per_division))
                for start in range(0, count, columns_per_division)
            ])
        ]
        targets = columns + (finals if self.combine.isChecked() else [])
        existing = [path for path in targets if path.exists()]
        self.replace_outputs = set()
        if existing:
            dialog = QMessageBox(self.window)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("Output files already exist")
            dialog.setText(
                "Replace these files and continue rendering?\n\n"
                + "\n".join(str(path) for path in existing)
            )
            replace = dialog.addButton("Replace files and continue", QMessageBox.ButtonRole.AcceptRole)
            cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
            dialog.setDefaultButton(cancel)
            dialog.setEscapeButton(cancel)
            dialog.exec()
            if dialog.clickedButton() != replace:
                return
            self.replace_outputs = set(existing)
        self.export_directory = tempfile.TemporaryDirectory(prefix="fastvideoassembly-")
        graph_root = Path(self.export_directory.name)
        config = self.render_config()
        self.export_jobs = []
        self.export_groups = []
        self.measurement_keys = {}
        self.audio_peaks = {}
        durations = [
            sum(clip_duration(clip, config) for clip in track)
            for track in self.assembler.tracks
        ]
        scheduled_measurements = set()
        self.column_cleanup = {}
        for division_start in range(0, count, columns_per_division):
            for index in range(division_start, division_start + columns_per_division):
                track, path = self.assembler.tracks[index], columns[index]
                group_start = len(self.export_jobs)
                graph_path = graph_root / f"column{index}.ffgraph"
                for clip in track:
                    if (
                        config.audio_codec != "none"
                        and config.normalization == "True Peak"
                        and clip.has_audio
                        and clip.path not in scheduled_measurements
                    ):
                        self.measurement_keys[len(self.export_jobs)] = clip.path
                        self.export_jobs.append(
                            (clip.path, clip.duration, peak_measurement_arguments(clip))
                        )
                        scheduled_measurements.add(clip.path)
                self.column_cleanup[len(self.export_jobs)] = [graph_path]
                self.export_jobs.append((
                    path, durations[index],
                    partial(column_arguments, track, path, graph_path, config, self.audio_peaks),
                ))
                self.export_groups.append((timeline_name(index), group_start, len(self.export_jobs)))
            if self.combine.isChecked():
                output = finals[division_start // columns_per_division]
                group_columns = columns[division_start:division_start + columns_per_division]
                duration = max(durations[division_start:division_start + columns_per_division])
                group_start = len(self.export_jobs)
                if config.audio_codec != "none" and config.normalization == "True Peak":
                    self.measurement_keys[len(self.export_jobs)] = output
                    self.export_jobs.append(
                        (
                            output,
                            duration,
                            mix_peak_arguments(group_columns, duration),
                        )
                    )
                args = partial(
                    composition_arguments,
                    group_columns,
                    duration,
                    output,
                    graph_root / f"composition{division_start // columns_per_division}.ffgraph",
                    config,
                )
                self.export_jobs.append((output, duration, args))
                if self.assembler.remove_timelines.isChecked():
                    self.column_cleanup[len(self.export_jobs) - 1] = group_columns
                self.export_groups.append(("FINAL" if count == columns_per_division else "FINAL " + "".join(timeline_name(i) for i in range(division_start, division_start + columns_per_division)), group_start, len(self.export_jobs)))
        self.export_index = 0
        self.stop_requested = False
        self.render_paused = False
        self.render_waiting = False
        self.progress.setValue(0)
        if not self.assembler.keep_logs.isChecked():
            self.log.clear()
        self.log_dock.show()
        self.running = True
        self.update_enabled()
        self.start_export_job()

    def start_export_job(self):
        self.group_name, self.group_start, self.group_end = next(
            group for group in self.export_groups
            if group[1] <= self.export_index < group[2]
        )
        if self.export_index == self.group_start:
            self.group_started = monotonic()
            self.progress.setRange(0, 1000)
            self.progress.setValue(0)
        self.stage_seconds = 0.0
        self.render_frames_per_second = 0.0
        self.progress_buffer = ""
        path, self.stage_duration, args = self.export_jobs[self.export_index]
        measuring = self.export_index in self.measurement_keys
        self.measuring_audio = measuring
        self.audio_items_processed = 0
        self.audio_analysis_started = monotonic()
        if callable(args):
            if (
                args.func is composition_arguments
                and self.render_config().audio_codec != "none"
                and self.render_config().normalization == "True Peak"
            ):
                args = args(peak=self.audio_peaks[path])
            else:
                args = args()
        self.stage_log = ""
        operation = "Measuring audio" if measuring else "Rendering"
        self.stage_description = f"{operation} - {path.name}"
        self.update_export_progress()
        self.runtime_timer.start()
        if measuring:
            self.start_measurement_batch()
            return
        self.log.appendPlainText(f"{operation} {path}\n")
        if path in self.replace_outputs:
            args[args.index("-n")] = "-y"
        self.process.start(self.ffmpeg, args)

    def start_measurement_batch(self):
        self.measurement_exit_code = 0
        self.measurement_last = self.export_index
        self.measurement_seconds = {}
        for index in range(self.export_index, min(len(self.export_jobs), self.export_index + self.analysis_workers.value())):
            if index not in self.measurement_keys:
                break
            path, _duration, args = self.export_jobs[index]
            process = QProcess(self)
            self.measurement_processes[process] = [index, "", ""]
            self.measurement_seconds[index] = 0.0
            process.readyReadStandardOutput.connect(partial(self.read_measurement, process))
            process.readyReadStandardError.connect(partial(self.read_measurement, process))
            process.finished.connect(partial(self.measurement_finished, process))
            self.measurement_last = index
            self.log.appendPlainText(f"Measuring audio {path}\n")
            process.start(self.ffmpeg, args)

    def read_measurement(self, process):
        state = self.measurement_processes[process]
        index = state[0]
        state[1] += bytes(process.readAllStandardOutput()).decode()
        text = bytes(process.readAllStandardError()).decode()
        state[2] += text
        self.log.appendPlainText(text)
        while "\n" in state[1]:
            line, state[1] = state[1].split("\n", 1)
            if line.startswith("out_time_us=") and line[12:].strip() != "N/A":
                self.measurement_seconds[index] = max(self.measurement_seconds[index], min(self.export_jobs[index][1] * 0.999, int(line[12:]) / 1_000_000))
        self.stage_seconds = sum(self.measurement_seconds.values())
        self.update_export_progress()

    def measurement_finished(self, process, exit_code, exit_status):
        self.read_measurement(process)
        index, _, log = self.measurement_processes.pop(process)
        process.deleteLater()
        self.log.appendPlainText(f"FFmpeg exited with code {exit_code}")
        if exit_code == 0 and not self.stop_requested:
            measured = json.loads(log[log.rindex("{"):log.rindex("}") + 1])
            self.audio_peaks[self.measurement_keys[index]] = float(measured["input_tp"])
            self.measurement_seconds[index] = self.export_jobs[index][1]
            self.audio_items_processed += 1
            self.update_runtime()
        if exit_code != 0:
            self.measurement_exit_code = exit_code
            self.measurement_last = index
        if self.measurement_processes:
            return
        self.stage_seconds = sum(self.measurement_seconds.values())
        self.update_export_progress()
        self.export_index = self.measurement_last
        self.advance_export(self.measurement_exit_code)

    def pause_export(self):
        self.render_paused = not self.render_paused
        self.update_enabled()
        if self.render_paused:
            self.window.statusBar().showMessage("Pausing after active work finishes")
        elif self.render_waiting:
            self.group_started += monotonic() - self.render_pause_started
            self.render_waiting = False
            self.start_export_job()

    def stop_export(self):
        self.stop_requested = True
        if self.render_waiting:
            self.end_export("Rendering stopped")
        elif self.measurement_processes:
            for process in self.measurement_processes:
                process.write(b"q\n")
        else:
            self.process.write(b"q\n")

    def read_progress(self):
        self.progress_buffer += bytes(self.process.readAllStandardOutput()).decode()
        while "\n" in self.progress_buffer:
            line, self.progress_buffer = self.progress_buffer.split("\n", 1)
            if line.startswith("fps="):
                self.render_frames_per_second = float(line[4:])
                self.update_runtime()
            if line.startswith("out_time_us=") and line[12:].strip() != "N/A":
                self.stage_seconds = max(
                    self.stage_seconds,
                    min(self.stage_duration * 0.999, int(line[12:]) / 1_000_000),
                )
                self.update_export_progress()

    def update_export_progress(self):
        total = sum(job[1] for job in self.export_jobs[self.group_start:self.group_end])
        completed = sum(job[1] for job in self.export_jobs[self.group_start:self.export_index]) + self.stage_seconds
        fraction = completed / total
        self.progress.setValue(min(999, int(fraction * 1000)) if fraction < 1 else 1000)
        self.update_runtime()

    def update_runtime(self):
        elapsed_seconds = monotonic() - self.group_started
        elapsed = timestamp(elapsed_seconds)
        total = sum(job[1] for job in self.export_jobs[self.group_start:self.group_end])
        completed = sum(job[1] for job in self.export_jobs[self.group_start:self.export_index]) + self.stage_seconds
        eta = timestamp(elapsed_seconds * (total - completed) / completed) if completed else "--:--:--"
        if self.measuring_audio:
            rate = self.audio_items_processed / (monotonic() - self.audio_analysis_started) if self.audio_items_processed else 0.0
            throughput = f"{rate:.1f} it/s"
        else:
            throughput = f"{self.render_frames_per_second:.1f} frames/s"
        self.progress.setFormat(
            f"{self.group_name} - %p% - ETA {eta} - {throughput}"
        )
        self.window.statusBar().showMessage(
            f"{self.stage_description}. Runtime {elapsed}"
        )

    def read_log(self):
        text = bytes(self.process.readAllStandardError()).decode()
        self.stage_log += text
        self.log.appendPlainText(text)

    def finished(self, exit_code, exit_status):
        self.read_progress()
        self.read_log()
        if exit_code == 0 and not self.stop_requested:
            self.stage_seconds = self.stage_duration
            self.update_export_progress()
        self.log.appendPlainText(f"FFmpeg exited with code {exit_code}")
        self.advance_export(exit_code)

    def advance_export(self, exit_code):
        if exit_code == 0 and not self.stop_requested and self.export_index in self.column_cleanup:
            for path in self.column_cleanup[self.export_index]:
                path.unlink()
        if (
            exit_code == 0
            and not self.stop_requested
            and self.export_index + 1 < len(self.export_jobs)
        ):
            self.export_index += 1
            if self.render_paused:
                self.runtime_timer.stop()
                self.render_waiting = True
                self.render_pause_started = monotonic()
                self.window.statusBar().showMessage("Rendering paused")
                self.update_enabled()
            else:
                self.start_export_job()
            return
        self.end_export(
            "Rendering stopped" if self.stop_requested else f"FFmpeg exited with code {exit_code}"
        )

    def end_export(self, result):
        self.runtime_timer.stop()
        self.running = False
        self.render_paused = False
        self.render_waiting = False
        self.export_directory.cleanup()
        self.export_directory = None
        self.window.statusBar().showMessage(
            f"{result} - {self.export_jobs[self.export_index][0]}"
        )
        self.update_enabled()

    def check_updates(self):
        dialog = UpdateDialog(self)
        dialog.exec()
        dialog.deleteLater()

    def install_explorer(self):
        integrations.install(self.launcher_module)
        self.window.statusBar().showMessage(
            "Installed FastVideoAssembly in File Explorer"
        )

    def eventFilter(self, watched, event):
        if (
            event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)
            and not self.loading
            and not self.running
            and event.mimeData().hasUrls()
            and all(url.isLocalFile() for url in event.mimeData().urls())
        ):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
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
            self.save_active_state()
        return super().eventFilter(watched, event)


def main():
    no_profile = "-NoProfile" in sys.argv[1:]
    paths = [arg for arg in sys.argv[1:] if arg != "-NoProfile"]
    if paths == ["--install-explorer"]:
        return integrations.install()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    controller = Application(paths=paths, no_profile=no_profile)
    controller.window.show()
    return app.exec()
