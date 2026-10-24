import json
import subprocess
from pathlib import Path

import pytest
import test_app
from PySide6.QtCore import QProcess, QUrl
from PySide6.QtMultimedia import QMediaPlayer
from test_audio import measure

from fastvideoassembly import app
from fastvideoassembly.assembly import (
    Clip,
    RenderConfig,
    column_arguments,
    division_arguments,
)

controller = test_app.controller
preview_source = test_app.preview_source


@pytest.mark.profile
def test_gain_apply_reset_and_restart(controller, preview_source, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.select_clip(clip)
    preview = controller.preview
    assert preview.audio_controls.isEnabled()
    assert not preview.apply_button.isEnabled()
    preview.gain_slider.setValue(-325)
    controller.select_clip(clip)
    assert preview.gain_spin.value() == -3.25
    assert controller.audio_gains == {}
    assert not controller.settings.contains("audio/gains")
    preview.reset_button.click()
    assert preview.gain_spin.value() == 0
    assert not preview.apply_button.isEnabled()
    preview.gain_spin.setValue(6)
    assert preview.gain_slider.value() == 600
    preview.apply_button.click()
    assert controller.audio_gains == {str(preview_source): 6}
    assert not preview.apply_button.isEnabled()
    qtbot.waitUntil(lambda: not preview.preparing_audio, timeout=15000)
    processed = Path(preview.player.source().toLocalFile())
    reference = preview_source.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(preview_source),
                    "-ac", "2", "-c:a", "pcm_f32le", str(reference)], check=True)
    assert float(measure(processed)["input_tp"]) - float(measure(reference)["input_tp"]) == pytest.approx(6, abs=0.1)
    preview.gain_spin.setValue(-12)
    preview.reset_button.click()
    assert preview.gain_spin.value() == 6
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.audio_gains == {str(preview_source): 6}
    assert restored.render_config().audio_gains == {str(preview_source): 6}
    controller.select_clip(None)
    assert not preview.audio_controls.isEnabled()


def test_saved_normalization_and_selection(controller, preview_source, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.normalization_cache = {
        json.dumps(["source-v1", controller.source_audio_key(clip)]): "-10.25"
    }
    controller.normalization.setCurrentText("True Peak")
    controller.select_clip(clip)
    preview = controller.preview
    assert preview.gain_spin.value() == 9.25
    assert "-10.25 dBTP" in preview.audio_level.toolTip()
    assert "-1.00 dBTP" in preview.audio_level.text()
    qtbot.waitUntil(lambda: not preview.preparing_audio, timeout=15000)
    preview.gain_spin.setValue(-5)
    controller.select_clip(None)
    controller.select_clip(clip)
    assert preview.gain_spin.value() == 9.25
    assert controller.audio_gains == {}
    qtbot.waitUntil(lambda: not preview.preparing_audio, timeout=15000)
    controller.select_clip(Clip(preview_source, 3, 60, 120, False))
    assert not preview.audio_controls.isEnabled()


@pytest.mark.parametrize("mode,direct", [
    ("None", False), ("True Peak", False), ("YouTube", False),
    ("None", True), ("True Peak", True),
])
def test_export_manual_gain(preview_source, tmp_path, mode, direct):
    clip = Clip(preview_source, 3, 60, 120, True)
    output = tmp_path / "gain.mp4"
    graph = tmp_path / "gain.ffgraph"
    config = RenderConfig(column_width=60, height=120, encoder="libx264",
                          normalization=mode, audio_gains={str(preview_source): -6})
    peaks = {}
    if direct:
        args = division_arguments([[clip], [clip]], 3, output, graph, config, peaks, peak=-10)
    else:
        args = column_arguments([clip], output, graph, config, peaks)
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    reference = tmp_path / "reference.mp4"
    config.audio_gains[str(preview_source)] = 0
    if direct:
        args = division_arguments([[clip], [clip]], 3, reference, graph, config, peaks, peak=-10)
    else:
        args = column_arguments([clip], reference, graph, config, peaks)
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    assert float(measure(output)["input_tp"]) - float(measure(reference)["input_tp"]) == pytest.approx(-6, abs=0.3)


def test_preview_cancels_obsolete_audio(controller, preview_source, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.audio_gains[str(preview_source)] = 6
    controller.select_clip(clip)
    process = controller.preview.audio_process
    assert process.waitForStarted()
    controller.select_clip(None)
    assert process.state() == QProcess.ProcessState.NotRunning
    assert controller.preview.audio_process is None
    assert controller.preview.player.source() == QUrl()
    controller.select_clip(clip)
    qtbot.waitUntil(lambda: not controller.preview.preparing_audio, timeout=15000)
    assert controller.preview.player.source().toLocalFile().endswith("preview.mkv")
    controller.preview.gain_spin.setValue(-6)
    controller.preview.apply_button.click()
    process = controller.preview.audio_process
    assert process.waitForStarted()
    controller.window.close()
    assert process.state() == QProcess.ProcessState.NotRunning
    assert controller.preview.player.source() == QUrl()


def test_preview_releases_loaded_media(controller, preview_source, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.audio_gains[str(preview_source)] = 6
    controller.select_clip(clip)
    preview = controller.preview
    qtbot.waitUntil(lambda: not preview.preparing_audio, timeout=15000)
    qtbot.waitUntil(lambda: preview.player.mediaStatus() in (
        QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia,
    ), timeout=15000)
    directory = Path(preview.audio_directory.name)
    controller.select_clip(None)
    assert not directory.exists()
    assert preview.audio_directory is None


@pytest.mark.profile
@pytest.mark.parametrize("interims", [False, True])
def test_manual_gain_cache_and_restart(controller, preview_source, tmp_path, qtbot, monkeypatch, interims):
    from dataclasses import replace

    other_path = tmp_path / "other.mp4"
    other_path.write_bytes(preview_source.read_bytes())
    first = Clip(preview_source, 0.5, 60, 120, True)
    other = Clip(other_path, 0.5, 60, 120, True)
    controller.clips = [first, other]
    controller.assembler.divisions.setValue(2)
    controller.assembler.tracks = [[first]] * 3 + [[other]] * 3
    controller.assembler.render_timelines.setChecked(interims)
    controller.normalization.setCurrentText("True Peak")
    controller.select_clip(first)
    controller.preview.gain_spin.setValue(-6)
    controller.preview.apply_button.click()
    qtbot.waitUntil(lambda: not controller.preview.preparing_audio, timeout=15000)
    config = RenderConfig(column_width=60, height=120, encoder="libx264", normalization="True Peak")
    monkeypatch.setattr(controller, "render_config", lambda: replace(config, audio_gains=dict(controller.audio_gains)))
    controller.start_export(tmp_path / "first.mp4")
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert controller.process.exitCode() == 0
    assert preview_source not in controller.measurement_keys.values()
    assert other_path in controller.measurement_keys.values()
    saved = dict(controller.normalization_cache)
    assert len(saved) == 3
    controller.preview.gain_spin.setValue(-12)
    controller.preview.apply_button.click()
    qtbot.waitUntil(lambda: not controller.preview.preparing_audio, timeout=15000)
    assert controller.normalization_cache == saved
    controller.start_export(tmp_path / "edited.mp4")
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert controller.process.exitCode() == 0
    assert list(controller.measurement_keys.values()) == [tmp_path / "edited_FINAL_ABC.mp4"]
    restored = app.Application()
    qtbot.addWidget(restored.window)
    monkeypatch.setattr(restored, "render_config", lambda: replace(config, audio_gains=dict(restored.audio_gains)))
    restored.start_export(tmp_path / "restored.mp4")
    qtbot.waitUntil(lambda: not restored.running, timeout=30000)
    assert restored.process.exitCode() == 0
    assert restored.measurement_keys == {}
    controller.select_clip(None)
