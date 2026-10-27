import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaPlayer

from fastvideoassembly import app
from fastvideoassembly.assembly import Clip, RenderConfig
from fastvideoassembly.classification import GPU_MODEL_ID


@pytest.mark.profile
def test_edit_preview_and_profile_workflow(controller, preview_source, tmp_path, qtbot):
    assert controller.window.isMinimized()
    assert not controller.window.isActiveWindow()

    controller.add_paths([preview_source])
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert controller.assembler.tracks == [[], [], []]
    assert controller.assembler.create_button.isEnabled()
    controller.assembler.create_button.click()
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    tracks = [list(track) for track in controller.assembler.tracks]
    added = tmp_path / "additional.mp4"
    added.hardlink_to(preview_source)
    controller.add_paths([added])
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert len(controller.clips) == 2
    assert controller.assembler.tracks == tracks
    controller.assembler.create_button.click()
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert sum(map(len, controller.assembler.tracks)) == 2
    assert controller.assembler.export_button.text() == "Render"
    controller.combine.setChecked(False)
    assert controller.assembler.export_button.text() == "Render"
    assert controller.assembler.stop_button.text() == "Stop"
    assert controller.assembler.stop_button.property("buttonSize") == "large"
    controller.running = True
    controller.update_enabled()
    assert not controller.assembler.create_button.isEnabled()
    controller.running = False

    controller.update_enabled()
    controller.project_name.setText("Regression project")

    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.assembler.tracks = [[clip], [], []]
    controller.refresh()
    controller.library.setCurrentRow(0)
    player = controller.preview.player
    qtbot.waitUntil(lambda: player.duration() > 0, timeout=15000)
    qtbot.waitUntil(
        lambda: controller.preview.video.videoSink().videoFrame().isValid(),
        timeout=15000,
    )
    assert player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
    controller.preview.play_button.click()
    qtbot.waitUntil(lambda: player.position() > 100, timeout=15000)
    qtbot.waitUntil(
        lambda: controller.preview.video.videoSink().videoFrame().isValid(),
        timeout=15000,
    )
    controller.preview.play_button.click()
    assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    assert "Preview paused" in controller.log.toPlainText()
    assert controller.window.statusBar().currentMessage() == "Preview paused"
    controller.preview.scrubber.setValue(1500)
    qtbot.waitUntil(lambda: abs(player.position() - 1500) < 100, timeout=5000)
    controller.preview.stop_button.click()
    assert player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    assert "Preview stopped" in controller.log.toPlainText()
    assert controller.window.statusBar().currentMessage() == "Preview stopped"
    assert player.position() == 0
    assert (
        controller.preview_dock.geometry().top()
        < controller.config_dock.geometry().top()
    )

    other = Clip(added, 3, 60, 120, True)
    controller.clips = [clip, other]
    controller.assembler.tracks = [[clip, other], [], []]
    controller.refresh()
    controller.library.setCurrentRow(0)
    controller.move_selected_clips("end")
    assert controller.assembler.tracks[0][-1] == clip

    assert controller.music_device.currentData() == "cpu"
    assert not controller.install_music_dependencies.isEnabled()
    assert not controller.music_precision.isEnabled()
    assert controller.music_threads.isEnabled()
    assert not controller.music_gpu_threads.isEnabled()
    controller.music_threads.setValue(8)
    controller.music_device.setCurrentIndex(1)
    assert controller.music_gpu_threads.value() == 1
    assert controller.music_gpu_threads.isEnabled()
    assert not controller.music_threads.isEnabled()
    controller.music_gpu_threads.setValue(2)
    assert controller.install_music_dependencies.isEnabled()
    assert controller.music_precision.isEnabled()
    assert controller.music_model.text() == GPU_MODEL_ID
    controller.music_precision.setCurrentIndex(1)
    controller.music_gpu_index.setValue(2)
    controller.music_device.setCurrentIndex(0)
    assert controller.music_precision.currentData() == "float16"
    controller.music_device.setCurrentIndex(1)
    assert controller.music_precision.currentData() == "float32"
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.music_device.currentData() == "cuda"
    assert restored.music_precision.currentData() == "float32"
    assert restored.music_gpu_index.value() == 2
    assert restored.music_threads.value() == 8
    assert restored.music_gpu_threads.value() == 2

    assert restored.project_name.text() == "Regression project"
    assert restored.assembler.tracks == controller.assembler.tracks
    restored.clear()
    assert restored.clips == []
    assert not any(restored.assembler.tracks)


@pytest.mark.profile
def test_gain_apply_reset_and_restart(
    controller, preview_source, tmp_path, qtbot, measure
):
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
    reference = tmp_path / "reference.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(preview_source),
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(reference),
        ],
        check=True,
    )
    assert float(measure(processed)["input_tp"]) - float(
        measure(reference)["input_tp"]
    ) == pytest.approx(6, abs=0.1)
    preview.gain_spin.setValue(-12)
    preview.reset_button.click()
    assert preview.gain_spin.value() == 6
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.audio_gains == {str(preview_source): 6}
    assert restored.render_config().audio_gains == {str(preview_source): 6}
    controller.select_clip(None)
    assert not preview.audio_controls.isEnabled()


def test_two_divisions_render_independent_triples(
    controller, preview_source, tmp_path, qtbot, monkeypatch
):
    combine = True
    render_timelines = True
    audio_codec = "aac"
    columns = 3
    import json

    controller.assembler.divisions.setValue(2)
    controller.assembler.columns.setCurrentText(str(columns))
    controller.combine.setChecked(combine)
    controller.assembler.render_timelines.setChecked(render_timelines)
    config = RenderConfig(
        column_width=60,
        height=120,
        encoder="libx264",
        speed="fast",
        normalization="True Peak",
        audio_codec=audio_codec,
    )
    monkeypatch.setattr(controller, "render_config", lambda: config)
    clips = []
    for i in range(columns * 2):
        path = tmp_path / f"source{i}.mp4"
        path.hardlink_to(preview_source)
        clips.append(Clip(path, 0.5 + i / 10, 60, 120, True))
    controller.assembler.tracks = [[clip] for clip in clips]
    letters = "ABCDEFGH"[: columns * 2]
    first, second = (letters[:columns], letters[columns:])
    first_final = tmp_path / f"division_FINAL_{first}.mp4"
    second_paths = {clip.path for clip in clips[columns:]}
    second_paths.update(tmp_path / f"division_{letter}.mp4" for letter in second)
    second_paths.add(tmp_path / f"division_FINAL_{second}.mp4")
    second_division_jobs = []
    start_job = controller.start_export_job

    def inspect_start():
        path, _, _ = controller.export_jobs[controller.export_index]
        if combine and path in second_paths:
            assert first_final.stat().st_size > 0
            second_division_jobs.append(path)
        start_job()

    monkeypatch.setattr(controller, "start_export_job", inspect_start)
    controller.start_export(tmp_path / "division.mp4")
    assert not controller.assembler.divisions.isEnabled()
    assert not controller.assembler.columns.isEnabled()
    expected_groups = [
        f"Division {division} - {name}"
        for division, letters in enumerate([first, second], 1)
        for name in (list(letters) if render_timelines else [])
        + ([f"FINAL {letters}"] if combine else [])
    ]
    assert [group[0] for group in controller.export_groups] == expected_groups
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.process.exitCode() == 0
    assert bool(second_division_jobs) == combine
    outputs = (list(letters) if render_timelines else []) + (
        [f"FINAL_{first}", f"FINAL_{second}"] if combine else []
    )
    assert {p.stem for p in tmp_path.glob("division_*.mp4")} == {
        f"division_{suffix}" for suffix in outputs
    }
    for suffix in outputs:
        data = json.loads(
            subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(tmp_path / f"division_{suffix}.mp4"),
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
        assert [stream["codec_type"] for stream in data["streams"]] == (
            ["video"] if audio_codec == "none" else ["video", "audio"]
        )
        assert data["streams"][0]["width"] == (
            60 * columns if suffix.startswith("FINAL") else 60
        )
        if suffix.startswith("FINAL"):
            assert float(data["format"]["duration"]) == pytest.approx(
                0.5 + (columns - 1 if suffix.endswith(first) else columns * 2 - 1) / 10,
                abs=0.06,
            )
    assert controller.assembler.divisions.isEnabled()
    assert controller.assembler.columns.isEnabled()


def test_direct_division_preserves_existing_interims(
    controller, preview_source, tmp_path, qtbot, monkeypatch
):
    normalization = "None"
    import json

    controller.assembler.render_timelines.setChecked(False)
    controller.assembler.remove_timelines.setChecked(True)
    controller.combine.setChecked(True)
    config = RenderConfig(
        column_width=60, height=120, encoder="libx264", normalization=normalization
    )
    monkeypatch.setattr(controller, "render_config", lambda: config)
    audible = Clip(preview_source, 0.5, 60, 120, True)
    silent = Clip(preview_source, 0.2, 60, 120, False)
    controller.assembler.tracks = [
        [audible, silent, audible],
        [audible],
        [silent, audible],
    ]
    controller.analysis_workers.setValue(8)
    for letter in "ABC":
        (tmp_path / f"direct_{letter}.mp4").write_bytes(b"existing interim")
    controller.start_export(tmp_path / "direct.mp4")
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.process.exitCode() == 0
    assert len(controller.export_jobs) == (3 if normalization == "True Peak" else 1)
    assert len(controller.audio_peaks) == (2 if normalization == "True Peak" else 0)
    for letter in "ABC":
        assert (tmp_path / f"direct_{letter}.mp4").read_bytes() == b"existing interim"
    data = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(tmp_path / "direct_FINAL.mp4"),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert [stream["codec_type"] for stream in data["streams"]] == ["video", "audio"]
    assert float(data["format"]["duration"]) == pytest.approx(1.2, abs=0.06)


def test_render_protection_stop_and_failure(
    controller, preview_source, tmp_path, qtbot, monkeypatch
):
    suffix = "_FINAL"
    with monkeypatch.context() as patch:
        output = tmp_path / "assembly.mp4"
        collision = tmp_path / f"assembly{suffix}.mp4"
        collision.write_bytes(b"existing output")
        error = Mock()
        patch.setattr(app.QMessageBox, "exec", lambda dialog: error(dialog))
        launch = Mock()
        patch.setattr(controller, "start_export_job", launch)
        controller.start_export(output)
        launch.assert_not_called()
        assert not controller.running
        assert controller.export_directory is None
        assert collision.read_bytes() == b"existing output"
        dialog = error.call_args.args[0]
        assert str(collision) in dialog.text()
        assert dialog.defaultButton() is dialog.button(
            app.QMessageBox.StandardButton.Cancel
        )
        assert dialog.escapeButton() is dialog.button(
            app.QMessageBox.StandardButton.Cancel
        )

    with monkeypatch.context() as patch:
        config = RenderConfig(
            column_width=60,
            height=120,
            encoder="libx264",
            speed="fast",
            audio_codec="none",
        )
        patch.setattr(controller, "render_config", lambda: config)
        controller.combine.setChecked(False)
        controller.assembler.tracks = [
            [Clip(preview_source, 0.3, 60, 120)] for _ in range(3)
        ]
        jobs = []
        start = controller.start_export_job

        def record_start():
            jobs.append(controller.export_index)
            start()

        patch.setattr(controller, "start_export_job", record_start)
        controller.start_export(tmp_path / "paused.mp4")
        controller.assembler.pause_button.click()
        assert "Pausing after active work finishes" in controller.log.toPlainText()
        controller.runtime_timer.timeout.emit()
        assert (
            controller.window.statusBar().currentMessage()
            == "Pausing after active work finishes"
        )
        qtbot.waitUntil(lambda: controller.render_waiting, timeout=15000)
        assert "Rendering paused" in controller.log.toPlainText()
        assert controller.window.statusBar().currentMessage() == "Rendering paused"
        temporary = Path(controller.export_directory.name)
        assert temporary.exists()
        assert controller.export_jobs[0][0].exists()
        assert jobs == [0]
        assert controller.export_index == 1
        assert controller.running
        assert controller.assembler.pause_button.text() == "Resume"
        assert not controller.assembler.scan_pause_button.isEnabled()
        assert not controller.assembler.create_button.isEnabled()
        assert controller.process.state() == app.QProcess.ProcessState.NotRunning
        controller.assembler.stop_button.click()
        assert (
            "Stop requested. Waiting for active work to exit"
            in controller.log.toPlainText()
        )
        assert "Rendering stopped" in controller.log.toPlainText()
        assert jobs == [0]
        assert not controller.running
        assert not controller.render_waiting
        assert not controller.render_paused
        assert not temporary.exists()
        assert controller.export_directory is None
        assert not controller.assembler.pause_button.isEnabled()
        assert not controller.assembler.stop_button.isEnabled()

    controller.assembler.tracks = [
        [Clip(tmp_path / "missing.mp4", 1, 90, 160)] for _ in range(3)
    ]
    output = tmp_path / "failed.mp4"
    controller.start_export(output)
    temporary = Path(controller.export_directory.name)
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert controller.process.exitCode() != 0
    assert controller.export_index == 0
    assert controller.export_directory is None
    assert not temporary.exists()
    assert not output.with_name("failed_A.mp4").exists()


def test_shared_test_defaults_skip_settings_and_window_activation(
    qtbot, monkeypatch, tmp_path
):
    settings = Mock()
    monkeypatch.setattr(app, "QSettings", settings)
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.window.show()
    assert controller.window.isMinimized()
    assert controller.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert not controller.window.isActiveWindow()
    controller.project_name.setText("Unsaved test project")
    controller.save_active_state()
    controller.window.close()
    settings.assert_not_called()
    assert list(tmp_path.iterdir()) == []
