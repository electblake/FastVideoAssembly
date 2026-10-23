"""Dock content for previewing the selected source video."""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class Preview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.title = QLabel("Select a clip to preview")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.video = QVideoWidget()
        self.video.setMinimumSize(160, 120)
        layout.addWidget(self.video, 1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.scrubber = QSlider(Qt.Orientation.Horizontal)
        self.scrubber.setAccessibleName("Preview position")
        self.scrubber.setRange(0, 0)
        self.scrubber.valueChanged.connect(self.player.setPosition)
        layout.addWidget(self.scrubber)
        controls = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.player.stop)
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        self.time = QLabel("00:00 / 00:00")
        controls.addWidget(self.time)
        layout.addLayout(controls)
        self.player.durationChanged.connect(self.update_position)
        self.player.positionChanged.connect(self.update_position)
        self.player.playbackStateChanged.connect(
            lambda state: self.play_button.setText(
                "Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play"
            )
        )
        self.set_clip(None)

    def set_clip(self, clip):
        source = QUrl.fromLocalFile(str(clip.path)) if clip else QUrl()
        if source != self.player.source():
            self.player.stop()
            self.player.setSource(source)
            if clip:
                self.player.pause()
        self.title.setText(clip.path.name if clip else "Select a clip to preview")
        self.title.setToolTip(str(clip.path) if clip else "")
        self.play_button.setEnabled(clip is not None)
        self.stop_button.setEnabled(clip is not None)
        self.scrubber.setEnabled(clip is not None)
        self.update_position()

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_position(self, *_):
        position, duration = self.player.position(), self.player.duration()
        if not self.scrubber.isSliderDown():
            self.scrubber.blockSignals(True)
            self.scrubber.setRange(0, duration)
            self.scrubber.setValue(position)
            self.scrubber.blockSignals(False)
        self.time.setText(
            f"{position // 60000:02d}:{position // 1000 % 60:02d} / "
            f"{duration // 60000:02d}:{duration // 1000 % 60:02d}"
        )
