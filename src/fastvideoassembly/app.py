"""Native Qt shell following FastVideoCropper's widget and appearance patterns."""

import json
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
from PySide6.QtCore import QEvent, QObject, QProcess, QSettings, Qt, QUrl
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
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import APP_NAME, APP_VERSION, integrations
from .assembly import (
    RenderConfig,
    clip_duration,
    clip_from_probe,
    column_jobs,
    composition_arguments,
    video_paths,
)
from .audio import mix_peak_arguments, peak_measurement_arguments
from .preview import Preview
from .three_column import COLUMN_NAMES, ThreeColumnAssembly


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
        self.pending = []
        self.loading = False
        self.running = False
        self.selected_clip = None
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
            self.assembler.splitter.restoreState(
                self.settings.value("mainWindow/splitterState")
            )
        self.refresh()
        saved_sources = self.settings.value("sources/paths", [], type=list)
        if saved_sources or paths:
            self.add_paths([*saved_sources, *paths], initialize_project=not saved_sources)

    def build_ui(self):
        file_menu = self.window.menuBar().addMenu("&File")
        self.open_action = QAction("&Add Videos…", self)
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
        self.open_button = QPushButton("Add Videos")
        self.open_button.clicked.connect(self.open_folder)
        library_layout.addWidget(self.open_button)
        self.library = QListWidget()
        self.library.setAccessibleName("Source videos")
        self.library.setAcceptDrops(True)
        self.library.viewport().setAcceptDrops(True)
        self.library.viewport().installEventFilter(self)
        self.library.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.library.currentRowChanged.connect(self.select_source)
        self.library.itemSelectionChanged.connect(self.select_source)
        library_layout.addWidget(self.library)
        self.remove_sources_button = QPushButton("Remove Selected Clips")
        self.remove_sources_button.clicked.connect(self.remove_selected_clip)
        library_layout.addWidget(self.remove_sources_button)
        self.clear_sources_button = QPushButton("Clear All Sources")
        self.clear_sources_button.clicked.connect(self.clear)
        library_layout.addWidget(self.clear_sources_button)
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
        self.assembler_tabs.addTab(self.assembler, "3 Column Assembly")
        self.window.setCentralWidget(self.assembler_tabs)
        process_panel = QWidget()
        process_layout = QVBoxLayout(process_panel)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        process_layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log_dock = QDockWidget("Process log", self.window)
        self.log_dock.setObjectName("processLog")
        process_layout.addWidget(self.log, 1)
        self.log_dock.setWidget(process_panel)
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
        self.encoder.addItem("NVIDIA HEVC - 10-bit", "hevc_nvenc")
        self.encoder.addItem("NVIDIA H.264 - 8-bit", "h264_nvenc")
        self.encoder.addItem("CPU H.264 - 8-bit", "libx264")
        self.speed = QComboBox()
        for value in ("fast", "balanced", "quality"):
            self.speed.addItem(value.title(), value)
        self.quality = QSpinBox()
        self.quality.setRange(1, 51)
        self.combine = QCheckBox("Create Final 3 Column Assembly Cut")
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
        self.normalization.setEnabled(self.audio_codec.currentData() != "none")
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
        if initialize_project and paths and not self.clips:
            source = Path(paths[0]).resolve()
            self.project_name.setText(
                source.name if source.is_dir() else source.parent.name
            )
        if not additions:
            return
        self.pending = additions
        self.settings.setValue(
            "sources/paths", [str(clip.path) for clip in self.clips] + [str(path) for path in additions]
        )
        self.settings.sync()
        self.progress.setFormat("%v / %m videos scanned")
        self.progress.setRange(0, len(additions))
        self.progress.setValue(0)
        self.loading = True
        self.update_enabled()
        self.probe_next()

    def probe_next(self):
        if not self.pending:
            self.loading = False
            self.refresh()
            self.window.statusBar().showMessage("Ready")
            return
        self.probing_path = self.pending.pop(0)
        self.log_dock.show()
        self.window.statusBar().showMessage(
            f"Scanning {self.progress.value()} / {self.progress.maximum()} complete - {self.probing_path.name}"
        )
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
        self.progress.setValue(self.progress.value() + 1)
        self.probe_next()

    def clear(self):
        self.selected_clip = None
        self.clips.clear()
        self.settings.setValue("sources/paths", [])
        self.settings.sync()
        self.assembler.tracks = [[], [], []]
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.window.statusBar().showMessage("Ready")
        self.refresh()

    def rebalance(self, longest_first=False):
        self.assembler.rebalance(self.clips, longest_first=longest_first)
        self.refresh()
        self.window.statusBar().showMessage("Ready")

    def refresh(self):
        selected_paths = {
            item.data(Qt.ItemDataRole.UserRole).path
            for item in self.library.selectedItems()
        }
        config = self.render_config()
        for index, label in enumerate(self.assembler.column_headers):
            label.setText(
                f"{"ABC"[index]} - {COLUMN_NAMES[index]}\n⅓ of output - {config.column_width} × {config.height}"
            )
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
        for column, (track, listing) in enumerate(
            zip(self.assembler.tracks, self.assembler.lists)
        ):
            listing.blockSignals(True)
            listing.clear()
            start = 0
            for number, clip in enumerate(track):
                duration = clip_duration(clip, config)
                item = QListWidgetItem(
                    f"{number + 1}. {clip.path.name}\n"
                    f"{timestamp(start)} → {timestamp(start + duration)} "
                    f"- {timestamp(duration)}"
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
                bar.setToolTip(f"{clip.path.name} - {timestamp(duration)}")
                self.assembler.timeline.addItem(bar)
                self.assembler.segment_bars.append((clip, bar))
                label = pg.TextItem(
                    str(number + 1),
                    color=palette.text().color(),
                    fill=palette.base().color(),
                    anchor=(0.5, 0.5),
                )
                label.setPos(start + duration / 2, 2 - column)
                self.assembler.timeline.addItem(label)
                start += duration
            listing.blockSignals(False)
            self.assembler.track_labels[column].setText(
                f"{COLUMN_NAMES[column]} - {len(track)} clips - {timestamp(durations[column])}"
            )
        self.assembler.timeline.setYRange(-0.6, 2.6, padding=0)
        self.assembler.timeline.setXRange(0, max(1, max(durations)), padding=0.02)
        self.select_clip(self.selected_clip)
        self.library.blockSignals(True)
        for row in range(self.library.count()):
            item = self.library.item(row)
            item.setSelected(item.data(Qt.ItemDataRole.UserRole).path in selected_paths)
        self.library.blockSignals(False)
        self.update_enabled()

    def select_source(self, row=None):
        items = self.library.selectedItems()
        current = self.library.currentItem()
        item = current if current in items else next(iter(items), None)
        self.select_clip(
            item.data(Qt.ItemDataRole.UserRole) if item is not None else None,
            sync_source=False,
        )

    def select_column(self, column, row):
        if row >= 0:
            self.select_clip(self.assembler.tracks[column][row])

    def select_clip(self, clip, sync_source=True):
        self.selected_clip = clip
        listings = [self.library, *self.assembler.lists] if sync_source else self.assembler.lists
        for listing in listings:
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
        for column, listing in enumerate(self.assembler.lists):
            if listing.currentRow() >= 0:
                self.assembler.active_column = column
        for source, bar in self.assembler.segment_bars:
            bar.setOpts(
                pen=pg.mkPen(
                    QApplication.palette().text().color(),
                    width=3 if source == clip else 1,
                )
            )
        self.preview.set_clip(clip)
        self.update_enabled()

    def remove_selected_clip(self):
        paths = {
            item.data(Qt.ItemDataRole.UserRole).path
            for item in self.library.selectedItems()
        }
        self.clips = [clip for clip in self.clips if clip.path not in paths]
        self.settings.setValue("sources/paths", [str(clip.path) for clip in self.clips])
        self.settings.sync()
        self.assembler.tracks = [
            [clip for clip in track if clip.path not in paths]
            for track in self.assembler.tracks
        ]
        self.selected_clip = None
        self.refresh()

    def reorder(self, offset):
        column = self.assembler.active_column
        row = self.assembler.lists[column].currentRow()
        track = self.assembler.tracks[column]
        track[row], track[row + offset] = track[row + offset], track[row]
        self.refresh()
        self.assembler.lists[column].setCurrentRow(row + offset)

    def move_column(self, offset):
        column = self.assembler.active_column
        row = self.assembler.lists[column].currentRow()
        clip = self.assembler.tracks[column].pop(row)
        target = column + offset
        self.assembler.tracks[target].append(clip)
        self.refresh()
        self.assembler.lists[target].setCurrentRow(
            len(self.assembler.tracks[target]) - 1
        )

    def timeline_clicked(self, event):
        if self.running or self.loading:
            return
        point = self.assembler.timeline.getViewBox().mapSceneToView(event.scenePos())
        column = 2 - round(point.y())
        if column in range(3) and abs(point.y() - (2 - column)) <= 0.325:
            config = self.render_config()
            start = 0
            for row, clip in enumerate(self.assembler.tracks[column]):
                duration = clip_duration(clip, config)
                if start <= point.x() < start + duration:
                    self.select_clip(clip)
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
        self.assembler.balance_button.setEnabled(idle and bool(self.clips))
        self.assembler.longest_button.setEnabled(idle and bool(self.clips))
        self.assembler.create_button.setEnabled(idle and any(clip.portrait for clip in self.clips))
        self.assembler.export_button.setEnabled(idle and all(self.assembler.tracks))
        self.assembler.stop_button.setEnabled(self.running)
        self.render_panel.setEnabled(idle)
        self.combine.setEnabled(idle)
        self.audio_panel.setEnabled(idle)
        self.output_panel.setEnabled(idle)
        self.library.setEnabled(idle)
        removable = idle and bool(self.library.selectedItems())
        self.assembler.remove_button.setEnabled(removable)
        self.assembler.remove_button.setText(
            "Remove Selected Clips" if len(self.library.selectedItems()) > 1
            else "Remove Selected Clip"
        )
        self.remove_sources_button.setEnabled(removable)
        self.clear_sources_button.setEnabled(idle and bool(self.clips))
        for listing in self.assembler.lists:
            listing.setEnabled(idle)
        column = self.assembler.active_column
        row = self.assembler.lists[column].currentRow()
        selected = idle and row >= 0 and len(self.library.selectedItems()) == 1
        self.assembler.up_button.setEnabled(selected and row > 0)
        self.assembler.down_button.setEnabled(
            selected and row < len(self.assembler.tracks[column]) - 1
        )
        self.assembler.left_button.setEnabled(selected and column > 0)
        self.assembler.right_button.setEnabled(selected and column < 2)

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
        self.export_groups = []
        self.measurement_keys = {}
        self.audio_peaks = {}
        durations = [
            sum(clip_duration(clip, config) for clip in track)
            for track in self.assembler.tracks
        ]
        scheduled_measurements = set()
        self.column_cleanup = {}
        for index, (track, path) in enumerate(zip(self.assembler.tracks, columns)):
            group_start = len(self.export_jobs)
            manifest = graph_root / f"column{index}.ffconcat"
            jobs = list(column_jobs(track, path, manifest, config, self.audio_peaks))
            temporary_paths = [manifest]
            for clip, job in zip(track, jobs[:-1]):
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
                self.export_jobs.append(job)
                temporary_paths.extend([job[0], job[0].with_suffix(".ffgraph")])
            self.column_cleanup[len(self.export_jobs)] = temporary_paths
            self.export_jobs.append(jobs[-1])
            self.export_groups.append(("ABC"[index], group_start, len(self.export_jobs)))
        if self.combine.isChecked():
            group_start = len(self.export_jobs)
            if config.audio_codec != "none" and config.normalization == "True Peak":
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
            self.export_groups.append(("FINAL", group_start, len(self.export_jobs)))
        self.export_index = 0
        self.stop_requested = False
        self.progress.setValue(0)
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
        self.progress_buffer = ""
        path, self.stage_duration, args = self.export_jobs[self.export_index]
        measuring = self.export_index in self.measurement_keys
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
        self.log.appendPlainText(f"{operation} {path}\n")
        self.process.start(self.ffmpeg, args)

    def stop_export(self):
        self.stop_requested = True
        self.process.write(b"q\n")

    def read_progress(self):
        self.progress_buffer += bytes(self.process.readAllStandardOutput()).decode()
        while "\n" in self.progress_buffer:
            line, self.progress_buffer = self.progress_buffer.split("\n", 1)
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
        eta = timestamp((monotonic() - self.group_started) * (total - completed) / completed) if completed else "--:--:--"
        self.progress.setFormat(f"{self.group_name} - %p% - ETA {eta}")
        self.window.statusBar().showMessage(
            f"{self.group_name} - {self.progress.value() // 10}% - ETA {eta} - {self.stage_description}"
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
        result = (
            "Rendering stopped"
            if self.stop_requested
            else f"FFmpeg exited with code {exit_code}"
        )
        self.window.statusBar().showMessage(
            f"{result} - {self.export_jobs[self.export_index][0]}"
        )
        self.update_enabled()

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
            self.settings.setValue("sources/paths", [str(clip.path) for clip in self.clips])
            self.settings.setValue("mainWindow/state", self.window.saveState(1))
            self.settings.setValue(
                "mainWindow/splitterState", self.assembler.splitter.saveState()
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
