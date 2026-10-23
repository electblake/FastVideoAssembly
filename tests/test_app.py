import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from fastvideoassembly import app
from fastvideoassembly.assembly import Clip, RenderConfig


@pytest.mark.parametrize("suffix", ["_FINAL", "_A", "_B", "_C"])
def test_collision_stops_before_any_render(controller, tmp_path, monkeypatch, suffix):
    output = tmp_path / "assembly.mp4"
    collision = tmp_path / f"assembly{suffix}.mp4"
    collision.write_bytes(b"existing output")
    error = Mock()
    monkeypatch.setattr(app.QMessageBox, "critical", error)
    launch = Mock()
    monkeypatch.setattr(controller, "start_export_job", launch)
    controller.start_export(output)
    launch.assert_not_called()
    assert not controller.running
    assert controller.export_directory is None
    assert collision.read_bytes() == b"existing output"
    assert str(collision) in error.call_args.args[2]


def test_columns_only_does_not_check_unused_final(controller, tmp_path, monkeypatch):
    output = tmp_path / "assembly.mp4"
    final = tmp_path / "assembly_FINAL.mp4"
    final.write_bytes(b"existing final")
    controller.combine.setChecked(False)
    controller.clips = [Clip(tmp_path / f"{i}.mp4", 1, 90, 160) for i in range(3)]
    controller.rebalance()
    launch = Mock()
    monkeypatch.setattr(controller, "start_export_job", launch)
    controller.start_export(output)
    launch.assert_called_once()
    assert len(controller.export_jobs) == 6
    assert final.read_bytes() == b"existing final"
    controller.running = False
    controller.export_directory.cleanup()


def test_output_settings_folder_default_and_direct_export(
    controller, tmp_path, monkeypatch
):
    folder = tmp_path / "My Project"
    folder.mkdir()
    controller.add_paths([folder])
    assert controller.project_name.text() == "My Project"
    assert controller.filename_format.text() == "{project}.Assembly.{date}.mp4"
    assert controller.output_dock.windowTitle() == "Output Settings"
    assert (
        controller.output_dock.geometry().top() > controller.audio_dock.geometry().top()
    )
    controller.output_folder.setText(str(tmp_path))
    frozen = Mock()
    frozen.today.return_value = date(2026, 10, 23)
    monkeypatch.setattr(app, "date", frozen)
    export = Mock()
    monkeypatch.setattr(controller, "start_export", export)
    dialog = Mock()
    monkeypatch.setattr(app.QFileDialog, "getSaveFileName", dialog)
    controller.choose_export()
    export.assert_called_once_with(tmp_path / "My Project.Assembly.2026-10-23.mp4")
    dialog.assert_not_called()
    controller.project_name.setText("Custom")
    controller.filename_format.setText("{date}.{project}.mp4")
    controller.choose_export()
    assert export.call_args.args[0] == tmp_path / "2026-10-23.Custom.mp4"
    assert controller.settings.value("output/project") == "Custom"
    assert controller.settings.value("output/format") == "{date}.{project}.mp4"
    assert controller.settings.value("output/folder") == str(tmp_path)


def test_missing_output_folder_stops_in_status_bar(controller, monkeypatch):
    controller.output_folder.clear()
    export = Mock()
    monkeypatch.setattr(controller, "start_export", export)
    controller.choose_export()
    export.assert_not_called()
    assert "Export stopped" in controller.window.statusBar().currentMessage()
    assert "output folder" in controller.window.statusBar().currentMessage()


def test_progress_resets_and_tracks_only_the_current_step(
    controller, tmp_path, monkeypatch
):
    process = Mock()
    monkeypatch.setattr(controller, "process", process)
    controller.export_jobs = [(tmp_path / f"step{i}.mp4", 100, []) for i in range(100)]
    controller.measurement_keys = {98: tmp_path / "audio.mp4"}
    controller.export_index = 98
    controller.progress.setValue(980)
    controller.start_export_job()
    assert controller.progress.value() == 0
    process.readAllStandardOutput.return_value = b"out_time_us=25000000\n"
    controller.read_progress()
    assert controller.progress.value() == 250
    controller.export_index = 99
    controller.start_export_job()
    assert controller.progress.value() == 0
    process.readAllStandardOutput.return_value = b"out_time_us=50000000\n"
    controller.read_progress()
    assert controller.progress.value() == 500
    process.readAllStandardOutput.return_value = b"out_time_us=100000000\n"
    controller.read_progress()
    assert controller.progress.value() == 1000


def test_output_browse_and_all_four_suffixes(controller, tmp_path, monkeypatch):
    monkeypatch.setattr(
        app.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path)
    )
    controller.output_browse.click()
    assert controller.output_folder.text() == str(tmp_path)
    controller.project_name.setText("Project")
    controller.filename_format.setText("{project}.Assembly.2026-10-23.mp4")
    controller.tracks = [
        [Clip(tmp_path / f"clip{i}.mp4", 1, 60, 120)] for i in range(3)
    ]
    controller.combine.setChecked(True)
    monkeypatch.setattr(controller, "start_export_job", Mock())
    controller.choose_export()
    outputs = [
        path.name for path, _, _ in controller.export_jobs if path.parent == tmp_path
    ]
    assert outputs == [
        f"Project.Assembly.2026-10-23_{suffix}.mp4"
        for suffix in ["A", "B", "C", "FINAL"]
    ]
    assert not controller.output_panel.isEnabled()
    controller.running = False
    controller.export_directory.cleanup()


def test_failed_clip_stops_queue_and_removes_temporary_files(
    controller, tmp_path, qtbot
):
    controller.tracks = [[Clip(tmp_path / "missing.mp4", 1, 90, 160)] for _ in range(3)]
    output = tmp_path / "failed.mp4"
    controller.start_export(output)
    temporary = Path(controller.export_directory.name)
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert controller.process.exitCode() != 0
    assert controller.export_index == 0
    assert controller.export_directory is None
    assert not temporary.exists()
    assert not output.with_name("failed_A.mp4").exists()


def test_true_peak_measures_each_clip_immediately_before_rendering(
    controller, tmp_path, monkeypatch
):
    controller.normalization.setCurrentText("True Peak")
    controller.combine.setChecked(False)
    clips = [Clip(tmp_path / f"source{i}.mp4", 1, 90, 160, True) for i in range(4)]
    controller.tracks = [[clips[0], clips[1]], [clips[2]], [clips[3], clips[0]]]
    monkeypatch.setattr(controller, "start_export_job", Mock())
    controller.start_export(tmp_path / "ordered.mp4")
    events = []
    for index, (path, _, args) in enumerate(controller.export_jobs):
        if index in controller.measurement_keys:
            events.append(f"measure {path.name}")
        elif callable(args):
            events.append(f"render {args.args[0].path.name}")
        else:
            events.append(f"save {path.name}")
    assert events == [
        "measure source0.mp4",
        "render source0.mp4",
        "measure source1.mp4",
        "render source1.mp4",
        "save ordered_A.mp4",
        "measure source2.mp4",
        "render source2.mp4",
        "save ordered_B.mp4",
        "measure source3.mp4",
        "render source3.mp4",
        "render source0.mp4",
        "save ordered_C.mp4",
    ]
    controller.running = False
    controller.export_directory.cleanup()


@pytest.mark.parametrize("mode", ["None", "True Peak", "YouTube"])
def test_column_a_is_saved_and_cleaned_before_b_failure(
    controller, tmp_path, monkeypatch, qtbot, mode
):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=60x120:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    config = RenderConfig(
        column_width=64, height=120, encoder="libx264", normalization=mode
    )
    monkeypatch.setattr(controller, "render_config", lambda: config)
    clip = Clip(source, 3, 60, 120, True)
    controller.tracks = [
        [clip],
        [Clip(tmp_path / "missing.mp4", 3, 60, 120, True)],
        [clip],
    ]
    output = tmp_path / "incremental.mp4"
    started_b = []
    start_job = controller.start_export_job

    def inspect_start():
        if controller.export_index == min(controller.column_cleanup) + 1:
            assert output.with_name("incremental_A.mp4").stat().st_size > 0
            assert not list(Path(controller.export_directory.name).glob("column0*"))
            started_b.append(True)
        start_job()

    monkeypatch.setattr(controller, "start_export_job", inspect_start)
    controller.start_export(output)
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert started_b == [True]
    assert controller.process.exitCode() != 0
    assert output.with_name("incremental_A.mp4").stat().st_size > 0
    assert not output.with_name("incremental_C.mp4").exists()
    assert not output.exists()
    assert controller.export_directory is None


@pytest.fixture
def controller(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "user_config_path", lambda *args, **kwargs: tmp_path)
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.window.show()
    return controller


@pytest.fixture
def preview_source(tmp_path):
    source = tmp_path / "preview.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=60x120:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    return source


@pytest.mark.parametrize("origin", ["source", "column", "timeline"])
def test_shared_selection_and_removal(controller, preview_source, tmp_path, origin):
    clips = [Clip(preview_source, 3, 60, 120, True)]
    for index in range(3):
        path = tmp_path / f"other{index}.mp4"
        path.hardlink_to(preview_source)
        clips.append(Clip(path, 3, 60, 120, True))
    controller.clips = clips
    controller.tracks = [[clips[1]], [clips[0], clips[2]], [clips[3]]]
    controller.refresh()
    if origin == "source":
        controller.library.setCurrentRow(0)
    elif origin == "column":
        controller.lists[1].setCurrentRow(0)
    else:
        event = Mock()
        event.scenePos.return_value = controller.timeline.getViewBox().mapViewToScene(
            QPointF(1, 1)
        )
        controller.timeline_clicked(event)
    assert controller.selected_clip == clips[0]
    assert controller.library.currentRow() == 0
    assert [listing.currentRow() for listing in controller.lists] == [-1, 0, -1]
    assert controller.active_column == 1
    assert controller.preview.player.source() == QUrl.fromLocalFile(str(preview_source))
    assert controller.down_button.isEnabled()
    assert controller.remove_button.isEnabled()
    controller.refresh()
    assert controller.selected_clip == clips[0]
    assert controller.lists[1].currentRow() == 0
    controller.remove_button.click()
    assert controller.clips == clips[1:]
    assert controller.tracks == [[clips[1]], [clips[2]], [clips[3]]]
    assert preview_source.exists()
    assert controller.selected_clip is None
    assert controller.preview.player.source().isEmpty()
    assert not controller.remove_button.isEnabled()


def test_preview_play_pause_scrub_and_stop(controller, preview_source, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.tracks = [[clip], [], []]
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
    controller.preview.scrubber.setValue(1500)
    qtbot.waitUntil(lambda: abs(player.position() - 1500) < 100, timeout=5000)
    controller.preview.stop_button.click()
    assert player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    assert player.position() == 0
    assert (
        controller.preview_dock.geometry().top()
        < controller.config_dock.geometry().top()
    )


def test_excluded_source_can_be_selected_and_removed(controller, preview_source):
    clip = Clip(preview_source, 3, 120, 60, True)
    controller.clips = [clip]
    controller.refresh()
    controller.library.setCurrentRow(0)
    assert controller.selected_clip == clip
    assert controller.remove_button.isEnabled()
    assert not controller.up_button.isEnabled()
    assert not controller.right_button.isEnabled()
    controller.remove_button.click()
    assert controller.clips == []
    assert preview_source.exists()


def test_import_shows_busy_progress_instead_of_previous_render_percentage(
    controller, preview_source, qtbot
):
    controller.progress.setValue(1000)
    controller.add_paths([preview_source])
    assert controller.progress.minimum() == controller.progress.maximum() == 0
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert controller.progress.maximum() == 1000
    assert controller.progress.value() == 1000


def test_timeline_uses_rendered_frame_boundaries_and_ignores_gaps(controller, tmp_path):
    first = Clip(tmp_path / "first.mp4", 0.101, 60, 120)
    second = Clip(tmp_path / "second.mp4", 0.101, 60, 120)
    controller.clips = [first, second]
    controller.tracks = [[first, second], [], []]
    controller.refresh()
    assert controller.summary.text() == "Output Length: 00:00.3"
    assert controller.segment_bars[0][1].opts["width"] == pytest.approx(4 / 30)
    assert controller.segment_bars[1][1].opts["x0"] == pytest.approx(4 / 30)
    event = Mock()
    event.scenePos.return_value = controller.timeline.getViewBox().mapViewToScene(
        QPointF(0.12, 2)
    )
    controller.timeline_clicked(event)
    assert controller.selected_clip == first
    event.scenePos.return_value = controller.timeline.getViewBox().mapViewToScene(
        QPointF(0.15, 1.6)
    )
    controller.timeline_clicked(event)
    assert controller.selected_clip == first
    event.scenePos.return_value = controller.timeline.getViewBox().mapViewToScene(
        QPointF(0.15, 2)
    )
    controller.timeline_clicked(event)
    assert controller.selected_clip == second


def test_empty_and_editable_tracks(controller):
    assert not controller.export_button.isEnabled()
    controller.clips = [Clip(Path(f"clip{n}.mp4"), n, 90, 160) for n in range(1, 7)]
    controller.rebalance()
    assert controller.export_button.isEnabled()
    controller.lists[0].setCurrentRow(0)
    original = list(controller.tracks[0])
    controller.down_button.click()
    assert controller.tracks[0] == original[::-1]
    selected = controller.tracks[0][1]
    controller.right_button.click()
    assert controller.tracks[1][-1] == selected
    assert sum(map(len, controller.tracks)) == 6
    controller.clear()
    assert not controller.export_button.isEnabled()
    assert controller.library.count() == 0


def test_appearance_preserves_assembly_and_uses_separate_settings(controller):
    controller.clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 4)]
    controller.rebalance()
    tracks = [list(track) for track in controller.tracks]
    controller.theme.setCurrentIndex(controller.theme.findData("nord"))
    controller.apply_appearance()
    assert controller.tracks == tracks
    assert controller.settings.value("appearance/theme") == "nord"
    assert "FastVideoAssembly" in controller.window.windowTitle()


def test_busy_locks_edits(controller):
    controller.running = True
    controller.update_enabled()
    assert not controller.open_action.isEnabled()
    assert not controller.clear_action.isEnabled()
    assert not controller.export_button.isEnabled()
    assert not controller.longest_button.isEnabled()
    assert controller.stop_button.isEnabled()
    controller.running = False


def test_order_buttons_keep_equal_track_totals(controller):
    assert controller.balance_button.text() == "Shortest First"
    assert controller.longest_button.text() == "Longest First"
    assert not controller.longest_button.isEnabled()
    controller.clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 19)]
    controller.rebalance()
    original = [list(track) for track in controller.tracks]
    controller.longest_button.click()
    assert controller.tracks != original
    assert all(
        [c.duration for c in track] == sorted((c.duration for c in track), reverse=True)
        for track in controller.tracks
    )
    assert [sum(c.duration for c in track) for track in controller.tracks] == [
        sum(c.duration for c in track) for track in original
    ]
    controller.balance_button.click()
    assert controller.tracks == original


def test_shared_configuration_persists_and_updates_dimensions(controller, qtbot):
    controller.resolution.setCurrentIndex(1)
    controller.frame_rate.setCurrentIndex(controller.frame_rate.findData("30000/1001"))
    controller.encoder.setCurrentIndex(controller.encoder.findData("libx264"))
    controller.quality.setValue(18)
    controller.combine.setChecked(False)
    assert controller.render_config().column_width == 1280
    assert "1280 × 2160" in controller.column_headers[0].text()
    assert "final" not in controller.export_button.text()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.render_config() == controller.render_config()
    assert not restored.combine.isChecked()
    assert restored.config_dock.objectName() == "sharedRenderConfiguration"
    controller.running = True
    controller.update_enabled()
    assert not controller.render_panel.isEnabled()
    controller.running = False


def test_audio_dock_modes_persistence_and_busy_state(controller, qtbot):
    assert controller.config_dock.windowTitle() == "Render Settings"
    assert controller.audio_dock.windowTitle() == "Audio Settings"
    assert [
        controller.normalization.itemText(i)
        for i in range(controller.normalization.count())
    ] == ["None", "True Peak", "YouTube"]
    controller.normalization.setCurrentText("YouTube")
    controller.audio_codec.setCurrentText("E-AC-3")
    assert controller.render_config().audio_codec == "eac3"
    assert controller.render_config().normalization == "YouTube"
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.normalization.currentText() == "YouTube"
    assert restored.audio_codec.currentText() == "E-AC-3"
    controller.running = True
    controller.update_enabled()
    assert not controller.audio_panel.isEnabled()
    controller.running = False
