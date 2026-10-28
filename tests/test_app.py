import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from ffmpeg import FFmpegError
from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaPlayer

from fastvideoassembly import app
from fastvideoassembly.assembly import Clip, RenderConfig
from fastvideoassembly.classification import GPU_MODEL_ID


@pytest.mark.profile
def test_edit_preview_and_profile_workflow(controller, preview_source, tmp_path, qtbot, monkeypatch):
    assert controller.window.isMinimized()
    assert not controller.window.isActiveWindow()
    assert not controller.remove_missing_button.isEnabled()

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
    controller.assembler.tracks = [[clip, other], [clip], [clip]]
    controller.refresh()
    added.unlink()
    controller.output_folder.setText(str(tmp_path))
    with monkeypatch.context() as patch:
        export = Mock()
        patch.setattr(controller, "start_export", export)
        controller.assembler.export_button.click()
        export.assert_called_once()
    assert controller.remove_missing_button.text() == "Remove missing (1)"
    assert controller.remove_missing_button.isEnabled()
    controller.remove_missing_button.click()
    assert controller.clips == [clip]
    assert controller.library.count() == 1
    assert controller.assembler.tracks == [[clip], [clip], [clip]]
    assert controller.remove_missing_button.text() == "Remove missing (0)"
    assert not controller.remove_missing_button.isEnabled()
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
    controller.select_clip(clip)
    directories = [Path(task.command.arguments[-1]).parent for task in preview.audio_tasks]
    assert directories
    controller.window.close()
    qtbot.waitUntil(lambda: not preview.audio_tasks and not controller.window.isVisible(), timeout=15000)
    assert all(not directory.exists() for directory in directories)


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
    controller.clips = clips
    controller.normalization.setCurrentText("True Peak")
    controller.refresh()
    controller.assembler.normalize_button.click()
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    measurements = dict(controller.normalization_cache)
    assert len(measurements) == 8
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
    assert not controller.measurement_keys
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
    assert controller.render_task.future.exception() is None
    assert controller.normalization_cache == measurements
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
    normalization = "True Peak"
    import json

    controller.assembler.render_timelines.setChecked(False)
    controller.assembler.remove_timelines.setChecked(True)
    controller.combine.setChecked(True)
    audible = Clip(preview_source, 0.5, 60, 120, True)
    silent = Clip(preview_source, 0.2, 60, 120, False)
    music_path = tmp_path / "music.mp4"
    music_path.hardlink_to(preview_source)
    music = Clip(music_path, 0.5, 60, 120, True)
    controller.clips = [audible, music]
    controller.assembler.tracks = [[music], [], []]
    key = json.dumps([
        "music-v2", app.MODEL_ID, app.MODEL_FILE, app.WINDOW_SECONDS,
        {"music": controller.music_label.text(), "talking": controller.talking_label.text()},
        app.BACKGROUND_LABELS, controller.source_audio_key(music),
    ])
    controller.classification_cache[key] = {"music": 0.99, "talking": 0.01}
    controller.refresh()
    controller.assembler.classify_timelines_button.click()
    qtbot.waitUntil(lambda: not controller.running)
    assert controller.audio_muted == {str(music_path)}
    classification = dict(controller.classification_cache)
    config = RenderConfig(
        column_width=60, height=120, encoder="libx264", normalization=normalization,
        audio_muted=set(controller.audio_muted),
    )
    monkeypatch.setattr(controller, "render_config", lambda: config)
    controller.assembler.tracks = [
        [music, silent, audible],
        [music],
        [silent, music],
    ]
    controller.analysis_workers.setValue(8)
    controller.normalization.setCurrentText(normalization)
    controller.refresh()
    controller.assembler.normalize_button.click()
    qtbot.waitUntil(lambda: not controller.running, timeout=15000)
    measurements = dict(controller.normalization_cache)
    assert len(measurements) == 2
    controller.assembler.normalize_button.click()
    assert not controller.running
    assert not controller.export_jobs
    assert controller.normalization_cache == measurements
    for letter in "ABC":
        (tmp_path / f"direct_{letter}.mp4").write_bytes(b"existing interim")
    controller.start_export(tmp_path / "direct.mp4")
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.render_task.future.exception() is None
    assert len(controller.export_jobs) == 1
    assert not controller.measurement_keys
    assert controller.classification_cache == classification
    assert controller.audio_muted == {str(music_path)}
    assert controller.normalization_cache == measurements
    import numpy as np

    samples = np.frombuffer(subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(tmp_path / "direct_FINAL.mp4"),
         "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout, dtype=np.float32)
    assert np.max(np.abs(samples[:24000])) < 0.0001
    assert np.max(np.abs(samples[38400:48000])) > 0.1
    with monkeypatch.context() as patch:
        launch = Mock()
        patch.setattr(controller, "start_export_job", launch)
        controller.start_export(tmp_path / "cached.mp4")
        launch.assert_called_once()
        assert not controller.measurement_keys
        controller.end_export("Checked cached render")
        config.audio_gains[str(preview_source)] = -6
        controller.start_export(tmp_path / "changed-gain.mp4")
        assert list(controller.measurement_keys.values()) == [tmp_path / "changed-gain_FINAL.mp4"]
        controller.end_export("Checked changed mix")
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
    controller.clips = [Clip(preview_source, 3, 60, 120, True)]
    controller.normalization.setCurrentText("True Peak")
    assert not controller.assembler.normalization_stop_button.isEnabled()
    controller.assembler.normalize_button.click()
    temporary = Path(controller.export_directory.name)
    assert controller.measurement_processes
    assert controller.assembler.normalization_stop_button.isEnabled()
    assert not controller.assembler.normalize_button.isEnabled()
    controller.assembler.normalization_stop_button.click()
    qtbot.waitUntil(lambda: not controller.running, timeout=15000)
    assert controller.stop_requested
    assert not controller.measurement_processes
    assert not controller.normalization_cache
    assert not temporary.exists()
    assert controller.assembler.normalize_button.isEnabled()
    assert not controller.assembler.normalization_stop_button.isEnabled()
    controller.assembler.normalize_button.click()
    qtbot.waitUntil(lambda: not controller.running, timeout=15000)
    assert controller.normalization_cache
    assert not controller.assembler.normalization_stop_button.isEnabled()

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
        # Stopping the launcher left FFmpeg holding a segment open and the UI locked.
        # Retire after: first release containing this fix
        controller.combine.setChecked(True)
        controller.assembler.render_timelines.setChecked(False)
        controller.assembler.tracks = [
            [Clip(preview_source, 3, 60, 120)] * 9 for _ in range(3)
        ]
        segment_arguments = app.division_segment_arguments

        def paced_segment(*args):
            arguments = segment_arguments(*args)
            arguments.insert(arguments.index("-i"), "-re")
            return arguments

        patch.setattr(app, "division_segment_arguments", paced_segment)
        controller.start_export(tmp_path / "stopped.mp4")
        temporary = Path(controller.export_directory.name)
        qtbot.waitUntil(lambda: controller.stage_seconds > 0, timeout=15000)
        controller.assembler.stop_button.click()
        qtbot.waitUntil(lambda: not controller.running, timeout=15000)
        assert controller.render_task.future.done()
        assert not controller.running
        assert controller.render_panel.isEnabled()
        assert controller.library.isEnabled()
        assert controller.assembler.export_button.isEnabled()
        assert not controller.assembler.stop_button.isEnabled()
        assert controller.export_index == 0
        assert controller.export_directory is None
        assert not temporary.exists()

        controller.assembler.tracks = [
            [Clip(preview_source, 0.3, 60, 120)] for _ in range(3)
        ]
        controller.start_export(tmp_path / "restarted.mp4")
        qtbot.waitUntil(lambda: not controller.running, timeout=15000)
        assert controller.render_task.future.exception() is None
        assert (tmp_path / "restarted_FINAL.mp4").exists()
        assert controller.export_directory is None

    controller.assembler.render_timelines.setChecked(True)
    controller.combine.setChecked(False)
    controller.assembler.tracks = [
        [Clip(tmp_path / "missing.mp4", 1, 90, 160)] for _ in range(3)
    ]
    output = tmp_path / "failed.mp4"
    with qtbot.captureExceptions() as exceptions:
        controller.start_export(output)
        temporary = Path(controller.export_directory.name)
        qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert len(exceptions) == 1
    assert isinstance(exceptions[0][1], FFmpegError)
    assert isinstance(controller.render_task.future.exception(), FFmpegError)
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
