"""Dock content for previewing the selected source video."""

import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import delete


class Preview(QWidget):
    activity = Signal(str)
    gain_applied = Signal(float)
    mute_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio_request = 0
        self.audio_filter = "anull"
        self.preparing_audio = False
        self.audio_directory = None
        self.audio_process = None
        self.clip = None
        self.audio_clip = None
        self.saved_gain = 0.0
        layout = QVBoxLayout(self)
        self.title = QLabel("Select a clip to preview")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.video = QVideoWidget()
        self.video.setMinimumSize(160, 120)
        layout.addWidget(self.video, 1)
        self.player = None
        self.audio = QAudioOutput(self)
        self.scrubber = QSlider(Qt.Orientation.Horizontal)
        self.scrubber.setAccessibleName("Preview position")
        self.scrubber.setRange(0, 0)
        self.scrubber.valueChanged.connect(lambda position: self.player.setPosition(position))
        layout.addWidget(self.scrubber)
        controls = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(lambda: self.player.stop())
        self.stop_button.clicked.connect(lambda: self.activity.emit("Preview stopped"))
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        self.time = QLabel("00:00:00 / 00:00:00")
        controls.addWidget(self.time)
        layout.addLayout(controls)
        self.audio_controls = QWidget()
        audio_layout = QVBoxLayout(self.audio_controls)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        self.mute_checkbox = QCheckBox("Mute")
        self.mute_checkbox.toggled.connect(self.mute_changed)
        audio_layout.addWidget(self.mute_checkbox)
        self.audio_level = QLabel()
        audio_layout.addWidget(self.audio_level)
        gain_row = QHBoxLayout()
        gain_label = QLabel("Audio gain")
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-6000, 6000)
        self.gain_slider.setAccessibleName("Audio gain")
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60, 60)
        self.gain_spin.setDecimals(2)
        self.gain_spin.setSingleStep(0.1)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.setAccessibleName("Audio gain")
        self.gain_spin.setToolTip("Apply a manual gain in place of this clip's normalization")
        gain_label.setBuddy(self.gain_spin)
        self.gain_slider.valueChanged.connect(lambda value: self.gain_spin.setValue(value / 100))
        self.gain_spin.valueChanged.connect(self.edit_gain)
        gain_row.addWidget(gain_label)
        gain_row.addWidget(self.gain_slider, 1)
        gain_row.addWidget(self.gain_spin)
        audio_layout.addLayout(gain_row)
        actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(lambda: self.gain_applied.emit(self.gain_spin.value()))
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Discard unapplied audio gain changes")
        self.reset_button.clicked.connect(lambda: self.gain_spin.setValue(self.saved_gain))
        actions.addStretch()
        actions.addWidget(self.apply_button)
        actions.addWidget(self.reset_button)
        audio_layout.addLayout(actions)
        layout.addWidget(self.audio_controls)
        self.set_source(QUrl())
        self.set_clip(None)

    def set_source(self, source):
        if self.player is not None:
            self.player.stop()
            self.player.setAudioOutput(None)
            self.player.setVideoOutput(None)
            delete(self.player)
            if self.audio_directory is not None:
                self.audio_directory.cleanup()
        self.audio_directory = None
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.durationChanged.connect(self.update_position)
        self.player.positionChanged.connect(self.update_position)
        self.player.playbackStateChanged.connect(
            lambda state: self.play_button.setText(
                "Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play"
            )
        )
        self.player.setSource(source)
        if not source.isEmpty():
            self.player.pause()

    def set_clip(self, clip):
        if clip != self.clip:
            self.cancel_audio()
            self.audio_filter = "anull"
            self.preparing_audio = False
        self.clip = clip
        source = QUrl.fromLocalFile(str(clip.path)) if clip else QUrl()
        if self.audio_filter == "anull" and source != self.player.source():
            self.set_source(source)
        self.title.setText(clip.path.name if clip else "Select a clip to preview")
        self.title.setToolTip(str(clip.path) if clip else "")
        self.play_button.setEnabled(clip is not None and not self.preparing_audio)
        self.stop_button.setEnabled(clip is not None)
        self.scrubber.setEnabled(clip is not None and not self.preparing_audio)
        self.audio_controls.setEnabled(False)
        self.update_position()

    def cancel_audio(self):
        self.audio_request += 1
        if self.audio_process is not None:
            self.audio_process.kill()
            self.audio_process.waitForFinished()
            self.audio_process = None

    def edit_gain(self, value):
        self.gain_slider.setValue(round(value * 100))
        changed = value != round(self.saved_gain, 2)
        self.apply_button.setEnabled(changed)
        self.reset_button.setEnabled(changed)

    def set_audio(self, gain, level, audio_filter, enabled, ffmpeg):
        reload_gain = (self.clip != self.audio_clip or gain != self.saved_gain
                       or audio_filter != self.audio_filter)
        self.audio_clip = self.clip
        self.saved_gain = gain
        self.gain_spin.setRange(min(-60, gain), max(60, gain))
        self.gain_slider.setRange(round(min(-60, gain) * 100), round(max(60, gain) * 100))
        if reload_gain:
            self.gain_spin.setValue(gain)
        self.edit_gain(self.gain_spin.value())
        self.audio_level.setText(level)
        self.audio_controls.setEnabled(enabled)
        if audio_filter == self.audio_filter:
            return
        self.audio_filter = audio_filter
        self.cancel_audio()
        request = self.audio_request
        self.set_source(QUrl())
        if audio_filter == "anull":
            self.preparing_audio = False
            self.set_source(QUrl.fromLocalFile(str(self.clip.path)))
            self.play_button.setEnabled(True)
            self.scrubber.setEnabled(True)
            return
        self.preparing_audio = True
        self.play_button.setEnabled(False)
        self.scrubber.setEnabled(False)
        self.activity.emit("Preparing preview audio")
        clip = self.clip

        directory = tempfile.TemporaryDirectory(prefix="fastvideoassembly-preview-")
        process = QProcess(self)
        self.audio_process = process
        process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedErrorChannel)
        process.finished.connect(
            lambda code, _: self.load_audio_preview(request, directory, process, code)
        )
        process.start(ffmpeg, [
            "-v", "error", "-n", "-i", str(clip.path),
            "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
            "-af", ("aresample=48000:async=1:first_pts=0,"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"atrim=duration={clip.duration},{audio_filter}"),
            "-c:a", "pcm_f32le", str(Path(directory.name) / "preview.mkv"),
        ])

    def load_audio_preview(self, request, directory, process, exit_code):
        process.deleteLater()
        if request != self.audio_request:
            return
        subprocess.CompletedProcess([process.program(), *process.arguments()], exit_code).check_returncode()
        self.audio_process = None
        self.preparing_audio = False
        self.set_source(QUrl.fromLocalFile(str(Path(directory.name) / "preview.mkv")))
        self.audio_directory = directory
        self.play_button.setEnabled(True)
        self.scrubber.setEnabled(True)
        self.activity.emit("Preview audio ready")

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.activity.emit("Preview paused")
        else:
            self.player.play()
            self.activity.emit("Preview playback requested")

    def update_position(self, *_):
        position, duration = self.player.position(), self.player.duration()
        if not self.scrubber.isSliderDown():
            self.scrubber.blockSignals(True)
            self.scrubber.setRange(0, duration)
            self.scrubber.setValue(position)
            self.scrubber.blockSignals(False)
        self.time.setText(
            f"{position // 3600000:02d}:{position // 60000 % 60:02d}:{position // 1000 % 60:02d} / "
            f"{duration // 3600000:02d}:{duration // 60000 % 60:02d}:{duration // 1000 % 60:02d}"
        )
