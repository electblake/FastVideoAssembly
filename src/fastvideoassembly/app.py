"""Native Qt shell following FastVideoCropper's widget and appearance patterns."""

import json
import sys
import tempfile
from pathlib import Path
from string import Template

import pyqtgraph as pg
import qt_themes
from platformdirs import user_config_path
from PySide6.QtCore import QEvent, QObject, QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import APP_NAME, APP_VERSION, integrations
from .assembly import (
    balance,
    clip_from_probe,
    export_arguments,
    track_durations,
    video_paths,
)

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
        library_layout.addWidget(self.library)
        self.library_dock = QDockWidget("Source videos", self.window)
        self.library_dock.setObjectName("sourceVideos")
        self.library_dock.setWidget(library_widget)
        self.window.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.library_dock
        )
        view_menu.addAction(self.library_dock.toggleViewAction())

        central = QWidget()
        layout = QVBoxLayout(central)
        title = QLabel("Three-column assembly")
        title_font = title.font()
        title_font.setPointSizeF(title_font.pointSizeF() * 1.5)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        description = QLabel(
            "Portrait videos only (aspect ratio < 1). Balance duration, then play "
            "each column shortest to longest."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        output_strip = QHBoxLayout()
        for index, name in enumerate(COLUMN_NAMES):
            label = QLabel(f"{index + 1} · {name}\n⅓ of output · 640 × 1080")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMargin(12)
            output_strip.addWidget(label, 1)
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
        edit_buttons = QHBoxLayout()
        self.balance_button = QPushButton("Balance shortest → longest")
        self.balance_button.clicked.connect(self.rebalance)
        edit_buttons.addWidget(self.balance_button)
        self.up_button = QPushButton("Move earlier")
        self.up_button.clicked.connect(lambda: self.reorder(-1))
        self.down_button = QPushButton("Move later")
        self.down_button.clicked.connect(lambda: self.reorder(1))
        self.left_button = QPushButton("Move to left column")
        self.left_button.clicked.connect(lambda: self.move_column(-1))
        self.right_button = QPushButton("Move to right column")
        self.right_button.clicked.connect(lambda: self.move_column(1))
        for button in (
            self.up_button,
            self.down_button,
            self.left_button,
            self.right_button,
        ):
            edit_buttons.addWidget(button)
        layout.addLayout(edit_buttons)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        output_info = QLabel(
            "Output: MP4 · H.264 · 1920 × 1080 · 30 fps · No audio\n"
            "Clips fit without cropping. Shorter columns hold their final frame. "
            "Double-click a clip to open its source."
        )
        output_info.setWordWrap(True)
        layout.addWidget(output_info)
        export_row = QHBoxLayout()
        self.export_button = QPushButton("Render three-column video…")
        self.export_button.setProperty("variant", "primary")
        self.export_button.setProperty("buttonSize", "large")
        self.export_button.clicked.connect(self.choose_export)
        export_row.addWidget(self.export_button, 1)
        self.stop_button = QPushButton("Stop rendering")
        self.stop_button.clicked.connect(lambda: self.process.write(b"q\n"))
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
        known = {clip.path for clip in self.clips}
        self.pending = [path for path in video_paths(paths) if path not in known]
        self.loading = True
        self.update_enabled()
        self.probe_next()

    def probe_next(self):
        if not self.pending:
            self.loading = False
            self.rebalance()
            return
        self.probing_path = self.pending.pop(0)
        self.window.statusBar().showMessage(f"Reading {self.probing_path.name}")
        self.probe.start(
            self.ffprobe,
            [
                "-v",
                "error",
                "-select_streams",
                "v:0",
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
        self.probe_next()

    def clear(self):
        self.clips.clear()
        self.tracks = [[], [], []]
        self.refresh()

    def rebalance(self):
        self.tracks = balance(self.clips)
        self.refresh()
        self.window.statusBar().showMessage("Ready")

    def refresh(self):
        self.library.clear()
        for clip in self.clips:
            eligibility = "Portrait" if clip.portrait else "Excluded: not portrait"
            item = QListWidgetItem(
                f"{clip.path.name}\n{timestamp(clip.duration)} · {eligibility}"
            )
            item.setToolTip(str(clip.path))
            self.library.addItem(item)
        eligible = sum(clip.portrait for clip in self.clips)
        self.library_summary.setText(
            f"{len(self.clips)} videos · {eligible} portrait · "
            f"{len(self.clips) - eligible} excluded"
        )
        durations = track_durations(self.tracks)
        self.timeline.clear()
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
                item = QListWidgetItem(
                    f"{number + 1}. {clip.path.name}\n"
                    f"{timestamp(start)} → {timestamp(start + clip.duration)} "
                    f"· {timestamp(clip.duration)}"
                )
                item.setData(Qt.ItemDataRole.UserRole, clip)
                item.setToolTip(str(clip.path))
                listing.addItem(item)
                brush = palette.highlight().color()
                brush.setAlpha(190 if number % 2 == 0 else 110)
                bar = pg.BarGraphItem(
                    x0=start,
                    width=clip.duration,
                    y=2 - column,
                    height=0.65,
                    brush=brush,
                    pen=palette.text().color(),
                )
                bar.setToolTip(f"{clip.path.name} · {timestamp(clip.duration)}")
                self.timeline.addItem(bar)
                label = pg.TextItem(
                    str(number + 1),
                    color=palette.text().color(),
                    fill=palette.base().color(),
                    anchor=(0.5, 0.5),
                )
                label.setPos(start + clip.duration / 2, 2 - column)
                self.timeline.addItem(label)
                start += clip.duration
            listing.blockSignals(False)
            self.track_labels[column].setText(
                f"{COLUMN_NAMES[column]} · {len(track)} clips · {timestamp(durations[column])}"
            )
        self.timeline.setYRange(-0.6, 2.6, padding=0)
        self.timeline.setXRange(0, max(1, max(durations)), padding=0.02)
        self.summary.setText(
            f"Output length: {timestamp(max(durations))} · "
            f"Column difference: {timestamp(max(durations) - min(durations))}"
            + (
                " · Add at least three portrait clips to fill all columns."
                if not all(self.tracks)
                else ""
            )
        )
        self.update_enabled()

    def select_column(self, column, row):
        if row >= 0:
            self.active_column = column
            for index, listing in enumerate(self.lists):
                if index != column:
                    listing.setCurrentRow(-1)
        self.update_enabled()

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
        if column in range(3):
            start = 0
            for row, clip in enumerate(self.tracks[column]):
                if start <= point.x() < start + clip.duration:
                    self.lists[column].setCurrentRow(row)
                    break
                start += clip.duration

    def open_source(self, item):
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(item.data(Qt.ItemDataRole.UserRole).path))
        )

    def update_enabled(self):
        idle = not self.loading and not self.running
        for widget in (self.open_button, self.open_action, self.clear_action):
            widget.setEnabled(idle)
        self.balance_button.setEnabled(idle and bool(self.clips))
        self.export_button.setEnabled(idle and all(self.tracks))
        self.stop_button.setEnabled(self.running)
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
        filename, _ = QFileDialog.getSaveFileName(
            self.window,
            "Render assembly to a new file",
            str(Path(self.settings.value("folder_path", "")) / "assembly.mp4"),
            "MP4 video (*.mp4)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if filename:
            self.start_export(Path(filename))

    def start_export(self, output):
        self.output = output
        self.export_directory = tempfile.TemporaryDirectory(prefix="fastvideoassembly-")
        args = export_arguments(
            self.tracks,
            output,
            Path(self.export_directory.name) / "composition.ffgraph",
        )
        self.progress_buffer = ""
        self.progress.setValue(0)
        self.log.clear()
        self.log_dock.show()
        self.running = True
        self.update_enabled()
        self.window.statusBar().showMessage(f"Rendering {output.name}")
        self.process.start(self.ffmpeg, args)

    def read_progress(self):
        self.progress_buffer += bytes(self.process.readAllStandardOutput()).decode()
        while "\n" in self.progress_buffer:
            line, self.progress_buffer = self.progress_buffer.split("\n", 1)
            if line.startswith("out_time_us=") and line[12:] != "N/A":
                seconds = int(line[12:]) / 1_000_000
                self.progress.setValue(
                    round(seconds / max(track_durations(self.tracks)) * 1000)
                )

    def read_log(self):
        self.log.appendPlainText(bytes(self.process.readAllStandardError()).decode())

    def finished(self, exit_code, exit_status):
        self.read_log()
        self.running = False
        self.export_directory.cleanup()
        self.export_directory = None
        self.window.statusBar().showMessage(
            f"FFmpeg exited with code {exit_code} · {self.output}"
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
