import subprocess
from datetime import date
from itertools import pairwise
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtMultimedia import QMediaPlayer

from fastvideoassembly import app
from fastvideoassembly.assembly import Clip, RenderConfig, balance


@pytest.mark.parametrize("suffix", ["_FINAL", "_A", "_B", "_C"])
def test_collision_stops_before_any_render(controller, tmp_path, monkeypatch, suffix):
    output = tmp_path / "assembly.mp4"
    collision = tmp_path / f"assembly{suffix}.mp4"
    collision.write_bytes(b"existing output")
    error = Mock()
    monkeypatch.setattr(app.QMessageBox, "exec", lambda dialog: error(dialog))
    launch = Mock()
    monkeypatch.setattr(controller, "start_export_job", launch)
    controller.start_export(output)
    launch.assert_not_called()
    assert not controller.running
    assert controller.export_directory is None
    assert collision.read_bytes() == b"existing output"
    dialog = error.call_args.args[0]
    assert str(collision) in dialog.text()
    assert dialog.defaultButton() is dialog.button(app.QMessageBox.StandardButton.Cancel)
    assert dialog.escapeButton() is dialog.button(app.QMessageBox.StandardButton.Cancel)


@pytest.mark.parametrize("columns", [3, 4])
@pytest.mark.parametrize("divisions", [1, 2])
def test_replace_conflicting_outputs_and_continue(controller, preview_source, tmp_path, qtbot, monkeypatch, columns, divisions):
    output = tmp_path / "replace.mp4"
    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    controller.assembler.divisions.setValue(divisions)
    letters = "ABCDEFGH"[:columns * divisions]
    suffix = "" if divisions == 1 else "_" + letters[-columns:]
    existing = [tmp_path / f"replace_{letters[-1]}.mp4", tmp_path / f"replace_FINAL{suffix}.mp4"]
    for path in existing:
        path.write_bytes(b"old output")
    unrelated = tmp_path / "unrelated.mp4"
    unrelated.write_bytes(b"keep this")
    controller.assembler.tracks = [[Clip(preview_source, 0.5, 60, 120, True)] for _ in range(columns * divisions)]
    config = RenderConfig(column_width=60, height=120, encoder="libx264", speed="fast", normalization="True Peak")
    monkeypatch.setattr(controller, "render_config", lambda: config)

    def replace(dialog):
        next(button for button in dialog.buttons() if button.text() == "Replace files and continue").click()
        return 0

    monkeypatch.setattr(app.QMessageBox, "exec", replace)
    start = Mock(wraps=controller.process.start)
    monkeypatch.setattr(controller.process, "start", start)
    controller.start_export(output)
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert controller.process.exitCode() == 0
    assert controller.replace_outputs == set(existing)
    for call in start.call_args_list:
        args = call.args[1]
        assert ("-y" in args) == (Path(args[-1]) in existing)
        assert ("-n" in args) == (Path(args[-1]) not in existing)
    assert all(path.read_bytes() != b"old output" for path in existing)
    assert unrelated.read_bytes() == b"keep this"


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
    assert len(controller.export_jobs) == 3
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


def test_project_from_folder_live_selection(controller, tmp_path, qtbot):
    folder = tmp_path / "Project" / "Day" / "Clips"
    folder.mkdir(parents=True)
    source = folder / "first.mp4"
    source.touch()
    controller.add_paths([source])
    controller.project_from_folder.click()
    assert controller.project_name.isReadOnly()
    assert controller.project_name.text() == "Clips"
    assert controller.project_folder_level.isEnabled()
    controller.project_name.setFocus()
    qtbot.keyClicks(controller.project_name, "blocked")
    assert controller.project_name.text() == "Clips"
    controller.project_folder_level.setFocus()
    qtbot.keyClick(controller.project_folder_level, Qt.Key.Key_Down)
    assert controller.project_name.text() == "Day"
    qtbot.keyClick(controller.project_folder_level, Qt.Key.Key_Down)
    assert controller.project_name.text() == "Project"
    assert controller.project_folder_level.maximum() == 0
    assert controller.project_folder_level.minimum() == 1 - len(source.parents)
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.project_from_folder.isChecked()
    assert restored.project_folder_level.value() == -2
    assert restored.project_name.text() == "Project"
    assert restored.project_name.isReadOnly()
    controller.project_from_folder.click()
    assert not controller.project_name.isReadOnly()
    assert controller.project_folder_level.isEnabled()
    controller.project_name.selectAll()
    qtbot.keyClicks(controller.project_name, "Manual")
    assert controller.project_name.text() == "Manual"


def test_project_from_folder_tracks_first_source(controller, tmp_path):
    controller.project_name.setText("Existing project")
    controller.project_from_folder.click()
    assert controller.project_name.isReadOnly()
    assert controller.project_folder_level.isEnabled()
    assert controller.project_name.text() == "Existing project"
    for name in ("First", "Second"):
        folder = tmp_path / name
        folder.mkdir()
        source = folder / "clip.mp4"
        source.touch()
        controller.add_paths([source])
    assert controller.project_name.text() == "First"
    controller.library.item(0).setSelected(True)
    controller.remove_selected_clip()
    assert controller.project_name.text() == "Second"
    controller.clear()
    assert controller.project_name.text() == "Second"
    assert controller.project_folder_level.isEnabled()


def test_open_output_folder_uses_current_local_path(controller, tmp_path, monkeypatch, qtbot):
    open_url = Mock(return_value=True)
    monkeypatch.setattr(app.QDesktopServices, "openUrl", open_url)
    controller.output_folder.clear()
    assert not controller.output_open.isEnabled()
    controller.output_open.click()
    open_url.assert_not_called()
    folder = tmp_path / "Output space #1"
    folder.mkdir()
    monkeypatch.setattr(app.QFileDialog, "getExistingDirectory", lambda *args: str(folder))
    controller.output_browse.click()
    assert controller.output_open.isEnabled()
    controller.output_open.click()
    assert open_url.call_args.args[0].isLocalFile()
    assert Path(open_url.call_args.args[0].toLocalFile()) == folder
    controller.output_folder.setText(str(tmp_path))
    controller.output_open.click()
    assert Path(open_url.call_args.args[0].toLocalFile()) == tmp_path
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.output_open.isEnabled()
    restored.output_open.click()
    assert Path(open_url.call_args.args[0].toLocalFile()) == tmp_path
    controller.output_folder.setText("   ")
    assert not controller.output_open.isEnabled()


def test_missing_output_folder_stops_in_status_bar(controller, monkeypatch):
    controller.output_folder.clear()
    export = Mock()
    monkeypatch.setattr(controller, "start_export", export)
    controller.choose_export()
    export.assert_not_called()
    assert "Export stopped" in controller.window.statusBar().currentMessage()
    assert "output folder" in controller.window.statusBar().currentMessage()


def test_progress_and_eta_span_timeline_jobs(controller, tmp_path, monkeypatch):
    monkeypatch.setattr(controller, "start_measurement_batch", Mock())
    process = Mock()
    monkeypatch.setattr(controller, "process", process)
    clock = [100.0]
    monkeypatch.setattr(app, "monotonic", lambda: clock[0])
    controller.export_jobs = [(tmp_path / f"step{i}.mp4", 100, []) for i in range(5)]
    controller.export_groups = [("A", 0, 2), ("B", 2, 4), ("FINAL", 4, 5)]
    controller.measurement_keys = {0: tmp_path / "audio.mp4"}
    controller.export_index = 0
    controller.start_export_job()
    assert "ETA --:--:--" in controller.progress.text()
    assert "Runtime" not in controller.progress.text()
    assert "Runtime 00:00:00" in controller.window.statusBar().currentMessage()
    assert "ETA" not in controller.window.statusBar().currentMessage()
    clock[0] = 110
    process.readAllStandardOutput.return_value = b"out_time_us=50000000\n"
    controller.read_progress()
    assert controller.progress.value() == 250
    assert "ETA 00:00:30" in controller.progress.text()
    assert "Runtime 00:00:10" in controller.window.statusBar().currentMessage()
    clock[0] = 111
    controller.runtime_timer.timeout.emit()
    assert "ETA 00:00:33" in controller.progress.text()
    assert "Runtime 00:00:11" in controller.window.statusBar().currentMessage()
    assert controller.progress.value() == 250
    controller.export_index = 1
    controller.start_export_job()
    assert controller.progress.value() == 500
    assert controller.progress.text().endswith(" - 0.0 frames/s")
    clock[0] = 120
    process.readAllStandardOutput.return_value = b"fps=147.25\nout_time_us=50000000\n"
    controller.read_progress()
    assert controller.progress.value() == 750
    assert controller.progress.text().endswith(" - 147.2 frames/s")
    process.readAllStandardOutput.return_value = b"fps=98."
    controller.read_progress()
    assert controller.progress.text().endswith(" - 147.2 frames/s")
    process.readAllStandardOutput.return_value = b"75\n"
    controller.read_progress()
    assert controller.progress.text().endswith(" - 98.8 frames/s")
    process.readAllStandardOutput.return_value = b"out_time_us=0\n"
    controller.read_progress()
    assert controller.progress.value() == 750
    for index, name in [(2, "B"), (4, "FINAL")]:
        controller.export_index = index
        controller.start_export_job()
        assert controller.progress.value() == 0
        assert controller.progress.text().startswith(name)
        assert "ETA --:--:--" in controller.progress.text()
        assert controller.progress.text().endswith(" - 0.0 frames/s")
        assert "Runtime 00:00:00" in controller.window.statusBar().currentMessage()


@pytest.mark.parametrize("stopped,exit_code", [(False, 0), (True, 0), (False, 1)])
def test_progress_completes_only_after_successful_exit(
    controller, tmp_path, monkeypatch, stopped, exit_code
):
    process = Mock()
    process.readAllStandardOutput.return_value = b"out_time_us=100000000\n"
    process.readAllStandardError.return_value = b""
    monkeypatch.setattr(controller, "process", process)
    controller.export_jobs = [(tmp_path / "final.mp4", 100, [])]
    controller.export_groups = [("FINAL", 0, 1)]
    controller.export_index = 0
    controller.measurement_keys = {}
    controller.column_cleanup = {}
    controller.export_directory = Mock()
    cleanup = controller.export_directory.cleanup
    controller.running = True
    controller.stop_requested = stopped
    controller.start_export_job()
    controller.finished(exit_code, None)
    assert controller.progress.value() == (1000 if not stopped and exit_code == 0 else 999)
    assert not controller.running
    cleanup.assert_called_once()
    assert not controller.runtime_timer.isActive()
    assert controller.export_directory is None
    if stopped:
        assert controller.window.statusBar().currentMessage().startswith("Rendering stopped")
    process.start.assert_called_once()


def test_output_browse_and_all_four_suffixes(controller, tmp_path, monkeypatch):
    monkeypatch.setattr(
        app.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path)
    )
    controller.output_browse.click()
    assert controller.output_folder.text() == str(tmp_path)
    controller.project_name.setText("Project")
    controller.filename_format.setText("{project}.Assembly.2026-10-23.mp4")
    controller.assembler.tracks = [
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


def test_true_peak_measurements_precede_single_timeline_render(
    controller, tmp_path, monkeypatch
):
    controller.normalization.setCurrentText("True Peak")
    controller.combine.setChecked(False)
    clips = [Clip(tmp_path / f"source{i}.mp4", 1, 90, 160, True) for i in range(4)]
    for clip in clips:
        clip.path.touch()
    controller.assembler.tracks = [
        [clips[0], clips[1]],
        [clips[2]],
        [clips[3], clips[0]],
    ]
    monkeypatch.setattr(controller, "start_export_job", Mock())
    controller.start_export(tmp_path / "ordered.mp4")
    events = []
    for index, (path, _, args) in enumerate(controller.export_jobs):
        if index in controller.measurement_keys:
            events.append(f"measure {path.name}")
        elif callable(args):
            events.append(f"render {path.name}")
        else:
            events.append(f"save {path.name}")
    assert events == [
        "measure source0.mp4",
        "measure source1.mp4",
        "render ordered_A.mp4",
        "measure source2.mp4",
        "render ordered_B.mp4",
        "measure source3.mp4",
        "render ordered_C.mp4",
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
    controller.assembler.tracks = [
        [clip],
        [Clip(tmp_path / "missing.mp4", 3, 60, 120, True)],
        [clip],
    ]
    (tmp_path / "missing.mp4").touch()
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
    status = controller.window.statusBar().currentMessage()
    assert status.startswith("FFmpeg exited with code ")
    assert not status.startswith("FFmpeg exited with code 0 ")
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


@pytest.mark.parametrize("origin", ["source", "timeline"])
def test_shared_selection_and_removal(controller, preview_source, tmp_path, origin):
    clips = [Clip(preview_source, 3, 60, 120, True)]
    for index in range(3):
        path = tmp_path / f"other{index}.mp4"
        path.hardlink_to(preview_source)
        clips.append(Clip(path, 3, 60, 120, True))
    controller.clips = clips
    controller.assembler.tracks = [[clips[1]], [clips[0], clips[2]], [clips[3]]]
    controller.refresh()
    if origin == "source":
        controller.library.setCurrentRow(0)
    else:
        event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
        event.scenePos.return_value = (
            controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(1, 1))
        )
        controller.timeline_clicked(event)
    assert controller.selected_clip == clips[0]
    assert controller.library.currentRow() == 0
    assert controller.preview.player.source() == QUrl.fromLocalFile(str(preview_source))
    assert controller.assembler.forward_button.isEnabled()
    assert controller.assembler.remove_button.isEnabled()
    controller.refresh()
    assert controller.selected_clip == clips[0]
    controller.assembler.remove_button.click()
    assert controller.clips == clips[1:]
    assert controller.assembler.tracks == [[clips[1]], [clips[2]], [clips[3]]]
    assert preview_source.exists()
    assert controller.selected_clip is None
    assert controller.preview.player.source().isEmpty()
    assert not controller.assembler.remove_button.isEnabled()


@pytest.mark.parametrize("button", ["source", "central"])
def test_shift_select_and_remove_sources(controller, preview_source, tmp_path, qtbot, button):
    clips = []
    for index in range(5):
        path = tmp_path / f"clip{index}.mp4"
        path.hardlink_to(preview_source)
        clips.append(Clip(path, 3, 60, 120, True))
    controller.clips = clips[:]
    controller.assembler.tracks = [[clips[0], clips[3]], [clips[1]], [clips[2], clips[4]]]
    controller.refresh()
    listing = controller.library
    qtbot.mouseClick(listing.viewport(), Qt.MouseButton.LeftButton,
                     pos=listing.visualItemRect(listing.item(1)).center())
    qtbot.mouseClick(listing.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ShiftModifier,
                     pos=listing.visualItemRect(listing.item(3)).center())
    assert [listing.row(item) for item in listing.selectedItems()] == [1, 2, 3]
    assert controller.selected_clip == clips[3]
    assert controller.preview.player.source() == QUrl.fromLocalFile(str(clips[3].path))
    controller.refresh()
    assert [listing.row(item) for item in listing.selectedItems()] == [1, 2, 3]
    controller.running = True
    controller.update_enabled()
    assert not controller.remove_sources_button.isEnabled()
    controller.running = False
    controller.update_enabled()
    remove = (controller.remove_sources_button if button == "source"
              else controller.assembler.remove_button)
    remove.click()
    assert controller.clips == [clips[0], clips[4]]
    assert controller.assembler.tracks == [[clips[0]], [], [clips[4]]]
    assert all(clip.path.exists() for clip in clips)
    assert not controller.remove_sources_button.isEnabled()
    assert controller.preview.player.source().isEmpty()


def test_preview_play_pause_scrub_and_stop(controller, preview_source, qtbot):
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
    assert controller.assembler.remove_button.isEnabled()
    assert not controller.assembler.forward_button.isEnabled()
    controller.assembler.remove_button.click()
    assert controller.clips == []
    assert preview_source.exists()


@pytest.mark.parametrize("enabled,count,workers", [(True, 2, 2), (True, 4, 4), (False, 4, 1)])
def test_parallel_source_scanning(
    controller, preview_source, tmp_path, qtbot, monkeypatch, enabled, count, workers
):
    from PySide6.QtCore import QThread

    assert controller.parallel_scanning.isChecked()
    assert controller.scan_threads.value() == 2
    controller.parallel_scanning.setChecked(enabled)
    controller.scan_threads.setValue(count)
    paths = [tmp_path / f"scan{i}.mp4" for i in range(5)]
    for path in paths:
        path.hardlink_to(preview_source)
    controller.add_paths(paths)
    updates = []
    parse = app.clip_from_probe

    def record_result(path, metadata):
        updates.append((path, QThread.currentThread()))
        return parse(path, metadata)

    monkeypatch.setattr(app, "clip_from_probe", record_result)
    controller.assembler.create_button.click()
    assert len(controller.probing_paths) == workers
    assert not controller.scan_threads.isEnabled()
    assert not controller.parallel_scanning.isEnabled()
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert [clip.path for clip in controller.clips] == paths
    assert all(isinstance(clip, Clip) for clip in controller.clips)
    assert {path for path, thread in updates} == set(paths)
    assert len(updates) == len(paths)
    assert all(thread == controller.thread() for path, thread in updates)
    assert sum(map(len, controller.assembler.tracks)) == len(paths)
    assert controller.progress.value() == len(paths)
    assert not controller.pending
    assert not controller.probing_paths
    assert controller.scan_threads.isEnabled()
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.scan_threads.value() == count
    assert restored.parallel_scanning.isChecked() == enabled
    controller.assembler.create_button.click()
    assert len(updates) == len(paths)
    extra = tmp_path / "later.mp4"
    extra.hardlink_to(preview_source)
    controller.add_paths([extra])
    controller.scan_threads.setValue(1)
    controller.assembler.create_button.click()
    assert len(controller.probing_paths) == 1
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert len(updates) == len(paths) + 1
    assert updates[-1][0] == extra
    assert sum(map(len, controller.assembler.tracks)) == len(paths) + 1


def test_parallel_scan_out_of_order_waits_for_all_workers(controller, tmp_path, monkeypatch):
    import json

    from fastvideoassembly.assembly import Source

    clock = [100.0]
    monkeypatch.setattr(app, "monotonic", lambda: clock[0])

    paths = [tmp_path / f"scan{i}.mp4" for i in range(4)]
    controller.clips = [Source(path) for path in paths]
    monkeypatch.setattr(app.QProcess, "start", Mock())
    monkeypatch.setattr(app.QProcess, "readAllStandardError", lambda self: b"")
    monkeypatch.setattr(
        app.QProcess, "readAllStandardOutput",
        lambda self: json.dumps({
            "streams": [{"codec_type": "video", "width": 60, "height": 120}],
            "format": {"duration": paths.index(controller.probing_paths[self]) + 1},
        }).encode(),
    )
    balance = Mock(wraps=controller.rebalance)
    monkeypatch.setattr(controller, "rebalance", balance)
    controller.create_timelines()
    assert controller.progress.text().endswith(" - 0.0 it/s")
    first, second = controller.probes
    clock[0] = 102.0
    second.finished.emit(0, app.QProcess.ExitStatus.NormalExit)
    assert controller.progress.text().endswith(" - 0.5 it/s")
    assert controller.probing_paths == {first: paths[0], second: paths[2]}
    controller.pause_scanning()
    clock[0] = 104.0
    second.finished.emit(0, app.QProcess.ExitStatus.NormalExit)
    assert controller.pending == [paths[3]]
    assert controller.loading
    balance.assert_not_called()
    clock[0] = 106.0
    first.finished.emit(0, app.QProcess.ExitStatus.NormalExit)
    assert controller.scanning_paused
    assert controller.progress.text().endswith(" - 0.5 it/s")
    clock[0] = 206.0
    controller.pause_scanning()
    clock[0] = 208.0
    first.finished.emit(0, app.QProcess.ExitStatus.NormalExit)
    assert not controller.loading
    balance.assert_called_once()
    assert [clip.path for clip in controller.clips] == paths
    assert [clip.duration for clip in controller.clips] == [1, 2, 3, 4]
    assert controller.progress.value() == 4
    assert controller.progress.text().endswith(" - 0.5 it/s")


@pytest.mark.parametrize("action", ["resume", "stop_paused", "stop_active"])
def test_scan_pause_stop_retains_progress(
    controller, preview_source, tmp_path, qtbot, monkeypatch, action
):
    paths = [tmp_path / f"pause{i}.mp4" for i in range(5)]
    for path in paths:
        path.hardlink_to(preview_source)
    controller.add_paths(paths)
    parse = Mock(wraps=app.clip_from_probe)
    monkeypatch.setattr(app, "clip_from_probe", parse)
    controller.assembler.create_button.click()
    if action == "stop_active":
        controller.assembler.scan_stop_button.click()
    else:
        controller.assembler.scan_pause_button.click()
        assert controller.assembler.scan_pause_button.text() == "Resume"
    qtbot.waitUntil(lambda: not controller.probing_paths, timeout=15000)
    assert parse.call_count == 2
    assert controller.progress.value() == 2
    assert controller.progress.maximum() == 5
    assert controller.pending == paths[2:]
    assert controller.assembler.tracks == [[], [], []]
    if action == "resume":
        assert controller.loading
        controller.assembler.scan_pause_button.click()
    else:
        if action == "stop_paused":
            controller.assembler.scan_stop_button.click()
        assert not controller.loading
        assert controller.assembler.create_button.isEnabled()
        controller.assembler.create_button.click()
        assert controller.progress.value() == 2
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert parse.call_count == 5
    assert {call.args[0] for call in parse.call_args_list} == set(paths)
    assert controller.progress.value() == 5
    assert sum(map(len, controller.assembler.tracks)) == 5
    assert not controller.assembler.scan_pause_button.isEnabled()
    assert not controller.assembler.scan_stop_button.isEnabled()
    assert controller.assembler.scan_pause_button.text() == "Pause"


@pytest.mark.parametrize("stop", [False, True])
def test_render_pause_resume_retains_jobs(
    controller, preview_source, tmp_path, qtbot, monkeypatch, stop
):
    config = RenderConfig(column_width=60, height=120, encoder="libx264", speed="fast", audio_codec="none")
    monkeypatch.setattr(controller, "render_config", lambda: config)
    controller.combine.setChecked(False)
    controller.assembler.tracks = [[Clip(preview_source, 0.3, 60, 120)] for _ in range(3)]
    jobs = []
    start = controller.start_export_job

    def record_start():
        jobs.append(controller.export_index)
        start()

    monkeypatch.setattr(controller, "start_export_job", record_start)
    controller.start_export(tmp_path / "paused.mp4")
    controller.assembler.pause_button.click()
    qtbot.waitUntil(lambda: controller.render_waiting, timeout=15000)
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
    if stop:
        log_before_stop = controller.log.toPlainText()
        controller.assembler.stop_button.click()
        assert controller.log.toPlainText() == log_before_stop
        assert jobs == [0]
    else:
        controller.assembler.pause_button.click()
        qtbot.waitUntil(lambda: not controller.running, timeout=30000)
        assert jobs == list(range(len(controller.export_jobs)))
        assert all((tmp_path / f"paused_{name}.mp4").exists() for name in "ABC")
    assert not controller.running
    assert not controller.render_waiting
    assert not controller.render_paused
    assert not temporary.exists()
    assert controller.export_directory is None
    assert not controller.assembler.pause_button.isEnabled()
    assert not controller.assembler.stop_button.isEnabled()


def test_import_counts_scanned_videos(
    controller, preview_source, qtbot
):
    controller.progress.setValue(1000)
    controller.add_paths([preview_source])
    assert controller.progress.value() == 1000
    assert not controller.loading
    controller.assembler.create_button.click()
    assert controller.progress.value() == 0
    assert controller.progress.maximum() == 1
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert controller.progress.maximum() == 1
    assert controller.progress.value() == 1
    assert controller.progress.text().startswith("1 / 1 videos scanned - ")
    assert controller.progress.text().endswith(" it/s")


def test_timeline_uses_rendered_frame_boundaries_and_ignores_gaps(controller, tmp_path):
    first = Clip(tmp_path / "first.mp4", 0.101, 60, 120)
    second = Clip(tmp_path / "second.mp4", 0.101, 60, 120)
    controller.clips = [first, second]
    controller.assembler.tracks = [[first, second], [], []]
    controller.refresh()
    assert controller.assembler.segment_bars[0][1].opts["width"] == pytest.approx(
        4 / 30
    )
    assert controller.assembler.segment_bars[1][1].opts["x0"] == pytest.approx(4 / 30)
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.scenePos.return_value = (
        controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(0.12, 2))
    )
    controller.timeline_clicked(event)
    assert controller.selected_clip == first
    event.scenePos.return_value = (
        controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(0.15, 1.6))
    )
    controller.timeline_clicked(event)
    assert controller.selected_clip == first
    event.scenePos.return_value = (
        controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(0.15, 2))
    )
    controller.timeline_clicked(event)
    assert controller.selected_clip == second


def test_empty_and_editable_tracks(controller):
    assert not controller.assembler.export_button.isEnabled()
    controller.clips = [Clip(Path(f"clip{n}.mp4"), n, 90, 160) for n in range(1, 7)]
    controller.rebalance()
    assert controller.assembler.export_button.isEnabled()
    controller.select_clip(controller.assembler.tracks[0][0])
    original = list(controller.assembler.tracks[0])
    controller.assembler.forward_button.click()
    assert controller.assembler.tracks[0] == original[::-1]
    assert sum(map(len, controller.assembler.tracks)) == 6
    controller.clear()
    assert not controller.assembler.export_button.isEnabled()
    assert controller.library.count() == 0


def test_assembler_tab_and_shared_process_dock(controller):
    assert controller.window.centralWidget() is controller.assembler_tabs
    assert controller.assembler_tabs.count() == 1
    assert controller.assembler_tabs.tabText(0) == "Column Assembly"
    assert controller.assembler_tabs.widget(0) is controller.assembler
    for widget in (
        controller.assembler.timeline,
        controller.assembler.export_button,
        controller.assembler.stop_button,
        controller.assembler.remove_button,
    ):
        assert controller.assembler.isAncestorOf(widget)
    assert not controller.assembler.isAncestorOf(controller.progress)
    process_layout = controller.log_dock.widget().layout()
    assert process_layout.itemAt(0).widget() is controller.progress
    assert process_layout.itemAt(1).widget() is controller.log
    for dock in (
        controller.library_dock,
        controller.preview_dock,
        controller.config_dock,
        controller.audio_dock,
        controller.output_dock,
    ):
        assert not controller.assembler.isAncestorOf(dock)


def test_activity_copy_and_clear(controller, monkeypatch):
    assert controller.log_dock.windowTitle() == "Activity"
    assert controller.log_dock.toggleViewAction().text() == "Activity"
    assert not controller.assembler.keep_logs.isChecked()
    controller.log.setPlainText("First line\nSecond line")
    copy = Mock()
    monkeypatch.setattr(controller.log, "copy", copy)
    controller.copy_output.click()
    assert controller.log.textCursor().selection().toPlainText() == "First line\nSecond line"
    copy.assert_called_once_with()
    controller.stage_log = "measurement data"
    controller.clear_output.click()
    assert controller.log.toPlainText() == ""
    assert controller.stage_log == "measurement data"


@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.parametrize("operation", ["scan", "cached_timelines", "render"])
def test_activity_retention_at_run_start(controller, tmp_path, monkeypatch, keep, operation):
    from fastvideoassembly.assembly import Source

    controller.assembler.keep_logs.setChecked(keep)
    controller.log.setPlainText("Previous run")
    clip = Clip(tmp_path / "source.mp4", 1, 60, 120, True)
    controller.clips = [Source(clip.path)] if operation == "scan" else [clip]
    if operation == "render":
        controller.assembler.tracks = [[clip], [clip], [clip]]
        monkeypatch.setattr(controller, "start_export_job", Mock())
        controller.start_export(tmp_path / "output.mp4")
        controller.running = False
        controller.export_directory.cleanup()
    else:
        monkeypatch.setattr(controller, "probe_next", Mock())
        controller.create_timelines()
        controller.loading = False
    assert controller.log.toPlainText() == ("Previous run" if keep else "")


def test_shared_sources_are_neutral_and_tab_filters_portrait(controller, tmp_path):
    clips = [
        Clip(tmp_path / "portrait.mp4", 3, 60, 120),
        Clip(tmp_path / "landscape.mp4", 4, 120, 60),
        Clip(tmp_path / "square.mp4", 5, 120, 120),
    ]
    controller.clips = clips
    for longest in (False, True):
        controller.rebalance(longest_first=longest)
        assert controller.clips == clips
        assert [controller.library.item(i).text() for i in range(3)] == [
            c.path.name for c in clips
        ]
        assert [c for track in controller.assembler.tracks for c in track] == clips[:1]
    controller.library.setCurrentRow(1)
    assert controller.selected_clip == clips[1]
    assert controller.assembler.remove_button.isEnabled()


def test_appearance_preserves_assembly_and_uses_separate_settings(controller):
    controller.clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 4)]
    controller.rebalance()
    tracks = [list(track) for track in controller.assembler.tracks]
    controller.theme.setCurrentIndex(controller.theme.findData("nord"))
    controller.apply_appearance()
    assert controller.assembler.tracks == tracks
    assert controller.settings.value("appearance/theme") == "nord"
    assert "FastVideoAssembly" in controller.window.windowTitle()


def test_busy_locks_edits(controller):
    controller.running = True
    controller.update_enabled()
    assert not controller.open_action.isEnabled()
    assert not controller.clear_action.isEnabled()
    assert not controller.assembler.export_button.isEnabled()
    assert not controller.assembler.longest_button.isEnabled()
    assert controller.assembler.stop_button.isEnabled()
    controller.running = False


def test_order_buttons_keep_equal_track_totals(controller):
    assert controller.assembler.balance_button.text() == "Shortest First"
    assert controller.assembler.longest_button.text() == "Longest First"
    assert not controller.assembler.longest_button.isEnabled()
    controller.clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 19)]
    controller.rebalance()
    original = [list(track) for track in controller.assembler.tracks]
    controller.assembler.longest_button.click()
    assert controller.assembler.tracks != original
    assert all(
        [c.duration for c in track] == sorted((c.duration for c in track), reverse=True)
        for track in controller.assembler.tracks
    )
    assert [
        sum(c.duration for c in track) for track in controller.assembler.tracks
    ] == [sum(c.duration for c in track) for track in original]
    controller.assembler.balance_button.click()
    assert controller.assembler.tracks == original


def test_shared_configuration_persists_and_updates_dimensions(controller, qtbot):
    controller.resolution.setCurrentIndex(1)
    controller.frame_rate.setCurrentIndex(controller.frame_rate.findData("30000/1001"))
    controller.encoder.setCurrentIndex(controller.encoder.findData("libx264"))
    controller.quality.setValue(18)
    controller.combine.setChecked(False)
    assert controller.render_config().column_width == 1280
    assert controller.render_config().column_width == 1280
    assert controller.render_config().height == 2160
    assert "final" not in controller.assembler.export_button.text()
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


def test_cpu_performance_settings_persist(controller, qtbot, monkeypatch):
    assert controller.filter_threads.value() == 4
    assert controller.analysis_workers.value() == 2
    assert not controller.analysis_workers.isEnabled()
    refresh = Mock()
    monkeypatch.setattr(controller, "refresh", refresh)
    controller.filter_threads.setValue(8)
    refresh.assert_not_called()
    assert controller.render_config().filter_threads == 4
    controller.quality.setValue(21)
    assert controller.settings.value("render/filter_threads", type=int) == 4
    refresh.reset_mock()
    controller.reset_filter_threads_button.click()
    assert controller.filter_threads.value() == 4
    refresh.assert_not_called()
    controller.filter_threads.setValue(8)
    controller.apply_filter_threads_button.click()
    refresh.assert_called_once()
    assert controller.render_config().filter_threads == 8
    refresh.reset_mock()
    controller.filter_threads.setValue(12)
    controller.reset_filter_threads_button.click()
    assert controller.filter_threads.value() == 8
    refresh.assert_not_called()
    controller.normalization.setCurrentText("True Peak")
    assert controller.analysis_workers.isEnabled()
    controller.analysis_workers.setValue(3)
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.render_config().filter_threads == 8
    assert restored.analysis_workers.value() == 3
    restored.audio_codec.setCurrentText("No Audio")
    assert not restored.analysis_workers.isEnabled()


@pytest.mark.parametrize("outcome", ["resume", "stop", "failure", "failure_first"])
def test_parallel_measurement_batch(controller, tmp_path, monkeypatch, outcome):
    clock = [100.0]
    monkeypatch.setattr(app, "monotonic", lambda: clock[0])
    controller.normalization.setCurrentText("True Peak")
    controller.assembler.tracks = [
        [Clip(tmp_path / f"{i}.mp4", 1, 60, 120, True) for i in range(3)],
        [Clip(tmp_path / "0.mp4", 1, 60, 120, True)],
        [Clip(tmp_path / "1.mp4", 1, 60, 120, True)],
    ]
    for i in range(3):
        (tmp_path / f"{i}.mp4").touch()
    workers = [Mock(), Mock(), Mock()]
    for worker in workers:
        worker.readAllStandardOutput.return_value = b""
        worker.readAllStandardError.return_value = b""
    factory = Mock(side_effect=workers)
    monkeypatch.setattr(app, "QProcess", factory)
    controller.start_export(tmp_path / "parallel.mp4")
    assert len(controller.measurement_processes) == 2
    assert factory.call_count == 2
    assert controller.progress.text().endswith(" - 0.0 it/s")
    clock[0] = 102.0
    controller.pause_export()
    if outcome == "stop":
        controller.stop_export()
        for worker in workers[:2]:
            worker.write.assert_called_once_with(b"q\n")
    workers[1].readAllStandardOutput.return_value = b"out_time_us=500000\n"
    controller.read_measurement(workers[1])
    assert controller.progress.value() == 83
    workers[1].readAllStandardOutput.return_value = b""
    workers[1].readAllStandardError.return_value = b'{"input_tp": "-6.0"}'
    controller.measurement_finished(workers[1], 1 if outcome == "failure" else 0, None)
    assert controller.progress.text().endswith(" - 0.5 it/s" if outcome in ("resume", "failure_first") else " - 0.0 it/s")
    assert controller.running
    assert controller.export_index == 0
    workers[0].readAllStandardError.return_value = b'{"input_tp": "-3.0"}'
    controller.measurement_finished(workers[0], 1 if outcome == "failure_first" else 0, None)
    assert not controller.measurement_processes
    if outcome == "resume":
        assert controller.progress.text().endswith(" - 1.0 it/s")
        assert controller.render_waiting
        assert not controller.runtime_timer.isActive()
        assert controller.export_index == 2
        assert controller.audio_peaks == {tmp_path / "0.mp4": -3, tmp_path / "1.mp4": -6}
        controller.pause_export()
        assert len(controller.measurement_processes) == 1
        assert factory.call_count == 3
        assert controller.progress.text().endswith(" - 0.0 it/s")
        controller.stop_export()
        controller.measurement_finished(workers[2], 0, None)
    assert not controller.running
    assert controller.export_directory is None
    if outcome in ("failure", "failure_first"):
        assert "code 1" in controller.window.statusBar().currentMessage()
        failed_path = tmp_path / ("0.mp4" if outcome == "failure_first" else "1.mp4")
        assert controller.window.statusBar().currentMessage().endswith(str(failed_path))


def test_parallel_true_peak_export(controller, preview_source, tmp_path, qtbot, monkeypatch):
    config = RenderConfig(column_width=60, height=120, encoder="libx264", speed="fast", normalization="True Peak", filter_threads=2)
    monkeypatch.setattr(controller, "render_config", lambda: config)
    clips = []
    for i in range(3):
        path = tmp_path / f"parallel_source{i}.mp4"
        path.hardlink_to(preview_source)
        clips.append(Clip(path, 0.5, 60, 120, True))
    controller.assembler.tracks = [clips, [clips[0]], [clips[1]]]
    controller.start_export(tmp_path / "parallel.mp4")
    assert len(controller.measurement_processes) == 2
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.process.exitCode() == 0
    assert set(controller.audio_peaks) == {clip.path for clip in clips} | {tmp_path / "parallel_FINAL.mp4"}
    assert (tmp_path / "parallel_FINAL.mp4").exists()

def test_click_current_clip_toggles_source_multi_selection(controller, tmp_path, qtbot, monkeypatch):
    monkeypatch.setattr(controller.preview, "set_clip", Mock())
    clips = [Clip(tmp_path / f"{i}.mp4", 3, 60, 120) for i in range(3)]
    controller.clips = clips[:]
    controller.assembler.tracks = [[clips[0]], [clips[1]], [clips[2]]]
    controller.refresh()
    library = controller.library
    library.setCurrentRow(0)
    library.item(1).setSelected(True)
    assert len(library.selectedItems()) == 2
    assert controller.assembler.remove_button.text() == "Remove selected"
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.scenePos.return_value = controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(1, 2))
    controller.timeline_clicked(event)
    assert [library.row(item) for item in library.selectedItems()] == [1]
    controller.assembler.remove_button.click()
    assert controller.clips == [clips[0], clips[2]]


def test_ctrl_deselect_updates_preview_and_disables_empty_selection(controller, tmp_path, qtbot, monkeypatch):
    preview = Mock()
    monkeypatch.setattr(controller.preview, "set_clip", preview)
    clips = [Clip(tmp_path / f"{i}.mp4", 3, 60, 120) for i in range(3)]
    controller.clips = clips[:]
    controller.assembler.tracks = [[clips[0]], [clips[1]], [clips[2]]]
    controller.refresh()
    listing = controller.library
    listing.setCurrentRow(0)
    for row in [2, 2, 0]:
        qtbot.mouseClick(listing.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier,
                         pos=listing.visualItemRect(listing.item(row)).center())
        selected = listing.selectedItems()
        if selected:
            assert controller.selected_clip in [item.data(Qt.ItemDataRole.UserRole) for item in selected]
    assert not listing.selectedItems()
    assert controller.selected_clip is None
    preview.assert_called_with(None)
    assert not controller.remove_sources_button.isEnabled()
    assert not controller.assembler.remove_button.isEnabled()
    controller.refresh()
    assert not listing.selectedItems()


def test_add_dialog_accepts_mixed_files_and_folders(controller, tmp_path, qtbot):
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QDialogButtonBox, QListView

    folder = tmp_path / 'folder'
    folder.mkdir()
    video = tmp_path / 'clip.mp4'
    video.touch()
    dialog = app.VideoSourceDialog(controller.window, str(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    view = dialog.findChild(QListView, 'listView')
    model = view.model()
    qtbot.waitUntil(lambda: model.index(str(video)).isValid())
    for path in [folder, video]:
        index = model.index(str(path))
        view.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert {Path(path) for path in dialog.selectedFiles()} == {folder, video}
    box = dialog.findChild(QDialogButtonBox)
    button = box.button(QDialogButtonBox.StandardButton.Open)
    assert button.isEnabled()
    button.click()
    assert dialog.result() == app.QDialog.DialogCode.Accepted
    assert {Path(path) for path in dialog.selectedFiles()} == {folder, video}


def test_source_list_drop_adds_files_and_folders_incrementally(controller, preview_source, tmp_path, qtbot, monkeypatch):
    from PySide6.QtCore import QMimeData, QPoint
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    probe = Mock()
    monkeypatch.setattr(controller.probe, 'start', probe)
    folder = tmp_path / 'folder'
    folder.mkdir()
    extra = folder / 'extra.mp4'
    extra.hardlink_to(preview_source)
    for paths, count in [([preview_source], 1), ([folder, preview_source], 2)]:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        for event in [
            QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
            QDragMoveEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
            QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
        ]:
            app.QApplication.sendEvent(controller.library.viewport(), event)
            assert event.isAccepted()
        assert not controller.loading
        assert controller.library.isEnabled()
        probe.assert_not_called()
        assert len(controller.clips) == count
    assert {clip.path for clip in controller.clips} == {preview_source, extra}
    assert controller.open_button.text() == 'Add Videos'


def test_duplicate_import_preserves_manual_order_and_progress(controller, tmp_path):
    path = tmp_path / 'clip.mp4'
    path.touch()
    clip = Clip(path, 3, 60, 120)
    controller.clips = [clip]
    controller.assembler.tracks = [[], [clip], []]
    controller.refresh()
    controller.progress.setValue(700)
    controller.add_paths([path, tmp_path])
    assert controller.assembler.tracks == [[], [clip], []]
    assert controller.progress.value() == 700
    assert not controller.loading


@pytest.mark.parametrize('local', [True, False])
def test_drop_always_imports_as_copy_and_rejects_remote_urls(controller, tmp_path, monkeypatch, local):
    from PySide6.QtCore import QEvent, QMimeData

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path)) if local else QUrl('https://example.com/video.mp4')])
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.type.return_value = QEvent.Type.Drop
    event.mimeData.return_value = mime
    add = Mock()
    monkeypatch.setattr(controller, 'add_paths', add)
    if local:
        assert controller.eventFilter(controller.library.viewport(), event)
        event.setDropAction.assert_called_once_with(Qt.DropAction.CopyAction)
        add.assert_called_once_with([str(tmp_path).replace('\\', '/')])
    else:
        # Use a real event for QObject's event filter when it is not a local import.
        from PySide6.QtGui import QDropEvent
        drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        assert not controller.eventFilter(controller.library.viewport(), drop)
        add.assert_not_called()


@pytest.mark.parametrize('origin', ['button', 'menu'])
def test_add_videos_entry_points_and_cancel(controller, tmp_path, monkeypatch, origin):
    dialog = Mock()
    dialog.exec.return_value = app.QDialog.DialogCode.Accepted
    dialog.directory.return_value.absolutePath.return_value = str(tmp_path)
    paths = [str(tmp_path / 'clip.mp4'), str(tmp_path / 'folder')]
    dialog.selectedFiles.return_value = paths
    monkeypatch.setattr(app, 'VideoSourceDialog', Mock(return_value=dialog))
    add = Mock()
    monkeypatch.setattr(controller, 'add_paths', add)
    trigger = controller.open_button.click if origin == 'button' else controller.open_action.trigger
    trigger()
    add.assert_called_once_with(paths)
    assert controller.open_action.text() == '&Add Videos...'
    dialog.deleteLater.assert_called_once()
    add.reset_mock()
    dialog.exec.return_value = app.QDialog.DialogCode.Rejected
    trigger()
    add.assert_not_called()


@pytest.mark.parametrize('seconds,expected', [(0, '00:00:00'), (59.99, '00:00:59'), (60, '00:01:00'), (3599.99, '00:59:59'), (3600, '01:00:00'), (6267.4, '01:44:27'), (90061, '25:01:01')])
def test_hour_duration_format(seconds, expected):
    assert app.timestamp(seconds) == expected


def test_preview_hour_duration_format(controller, monkeypatch):
    monkeypatch.setattr(controller.preview.player, 'position', lambda: 3600000)
    monkeypatch.setattr(controller.preview.player, 'duration', lambda: 6267400)
    controller.preview.update_position()
    assert controller.preview.time.text() == '01:00:00 / 01:44:27'


def test_import_waits_for_explicit_timeline_creation(controller, preview_source, tmp_path, qtbot):
    controller.add_paths([preview_source])
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert controller.assembler.tracks == [[], [], []]
    assert controller.assembler.create_button.isEnabled()
    controller.assembler.create_button.click()
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    tracks = [list(track) for track in controller.assembler.tracks]
    added = tmp_path / 'additional.mp4'
    added.hardlink_to(preview_source)
    controller.add_paths([added])
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert len(controller.clips) == 2
    assert controller.assembler.tracks == tracks
    controller.assembler.create_button.click()
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert sum(map(len, controller.assembler.tracks)) == 2
    assert controller.assembler.export_button.text() == 'Render'
    controller.combine.setChecked(False)
    assert controller.assembler.export_button.text() == 'Render'
    assert controller.assembler.stop_button.text() == 'Stop'
    assert controller.assembler.stop_button.property('buttonSize') == 'large'
    controller.running = True
    controller.update_enabled()
    assert not controller.assembler.create_button.isEnabled()
    controller.running = False


def test_source_list_restores_on_restart_without_creating_timelines(controller, preview_source, tmp_path, qtbot):
    extra = tmp_path / 'extra.mp4'
    extra.hardlink_to(preview_source)
    controller.add_paths([preview_source, extra])
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    controller.library.setCurrentRow(1)
    controller.remove_sources_button.click()
    controller.project_name.setText('Custom project')
    controller.window.close()
    assert controller.settings.value('sources/paths', type=list) == [str(preview_source)]
    restored = app.Application(paths=[preview_source, extra])
    qtbot.addWidget(restored.window)
    qtbot.waitUntil(lambda: not restored.loading, timeout=15000)
    assert [clip.path for clip in restored.clips] == [preview_source, extra]
    assert restored.project_name.text() == 'Custom project'
    assert restored.assembler.tracks == [[], [], []]
    assert restored.library.count() == 2
    restored.clear()
    restored.window.close()
    empty = app.Application()
    qtbot.addWidget(empty.window)
    assert empty.clips == []
    assert not empty.loading


def test_source_changes_persist_without_closing(controller, preview_source, tmp_path, qtbot):
    from PySide6.QtCore import QSettings

    second = tmp_path / 'second.mp4'
    second.hardlink_to(preview_source)
    controller.add_paths([second, preview_source])
    saved = QSettings(controller.settings.fileName(), QSettings.Format.IniFormat)
    assert saved.value('sources/paths', type=list) == [str(second), str(preview_source)]
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    controller.library.setCurrentRow(0)
    controller.remove_sources_button.click()
    saved.sync()
    assert saved.value('sources/paths', type=list) == [str(preview_source)]
    controller.clear()
    saved.sync()
    assert saved.value('sources/paths', type=list) == []


def test_scanned_sources_restore_and_only_scan_remaining(controller, preview_source, tmp_path, qtbot, monkeypatch):
    from fastvideoassembly.assembly import Source

    paths = [tmp_path / f"cached{i}.mp4" for i in range(3)]
    for path in paths:
        path.hardlink_to(preview_source)
    controller.add_paths(paths)
    controller.create_timelines()
    controller.stop_scanning()
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert sum(isinstance(clip, Clip) for clip in controller.clips) == 2
    assert isinstance(controller.clips[2], Source)
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.clips == controller.clips
    assert not restored.loading
    assert restored.assembler.tracks == [[], [], []]
    parse = Mock(wraps=app.clip_from_probe)
    monkeypatch.setattr(app, "clip_from_probe", parse)
    restored.create_timelines()
    qtbot.waitUntil(lambda: not restored.loading, timeout=15000)
    assert parse.call_count == 1
    assert parse.call_args.args[0] == paths[2]
    complete = app.Application()
    qtbot.addWidget(complete.window)
    assert complete.clips == restored.clips
    complete.create_timelines()
    assert not complete.loading
    assert parse.call_count == 1
    assert sum(map(len, complete.assembler.tracks)) == 3
    complete.library.setCurrentRow(1)
    complete.remove_selected_clip()
    removed = app.Application()
    qtbot.addWidget(removed.window)
    assert [clip.path for clip in removed.clips] == [paths[0], paths[2]]
    assert all(isinstance(clip, Clip) for clip in removed.clips)
    removed.clear()
    empty = app.Application()
    qtbot.addWidget(empty.window)
    assert empty.clips == []
    assert empty.settings.beginReadArray("sources/scanned") == 0
    empty.settings.endArray()


def test_render_settings_use_typed_ini_values(controller, qtbot):
    controller.encoder.setCurrentIndex(controller.encoder.findData("libx264"))
    controller.quality.setValue(17)
    controller.filter_threads.setValue(6)
    controller.apply_filter_threads_button.click()
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.render_config() == controller.render_config()
    assert not restored.settings.contains("render/config")
    assert restored.settings.value("render/quality", type=int) == 17
    assert restored.settings.value("render/filter_threads", type=int) == 6
    assert Path(restored.settings.fileName()).suffix == ".ini"


def test_hardware_render_settings_persist_and_control_scaling_options(controller, qtbot, monkeypatch):
    monkeypatch.setattr(app, "render_hardware", lambda ffmpeg: (
        [("CPU", "none"), ("NVIDIA NVDEC", "cuda"), ("Intel Quick Sync", "qsv")],
        [("CPU", "cpu"), ("NVIDIA CUDA", "cuda"), ("Intel Quick Sync", "qsv")],
    ))
    configured = app.Application()
    qtbot.addWidget(configured.window)
    assert configured.render_config().decoder == "none"
    assert configured.render_config().scaler == "cpu"
    assert configured.scaling_algorithm.isEnabled()
    assert not configured.qsv_scaling_mode.isEnabled()
    configured.decoder.setCurrentIndex(configured.decoder.findData("cuda"))
    configured.scaler.setCurrentIndex(configured.scaler.findData("qsv"))
    assert not configured.scaling_algorithm.isEnabled()
    assert configured.qsv_scaling_mode.isEnabled()
    configured.qsv_scaling_mode.setCurrentIndex(configured.qsv_scaling_mode.findData("low_power"))
    configured.scaler.setCurrentIndex(configured.scaler.findData("cuda"))
    assert configured.scaling_algorithm.isEnabled()
    assert not configured.qsv_scaling_mode.isEnabled()
    configured.scaling_algorithm.setCurrentIndex(configured.scaling_algorithm.findData("lanczos"))
    configured.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.render_config() == configured.render_config()
    assert restored.render_config().decoder == "cuda"
    assert restored.render_config().scaler == "cuda"
    assert restored.render_config().scaling_algorithm == "lanczos"
    assert restored.render_config().qsv_scaling_mode == "low_power"


def test_unavailable_saved_hardware_remains_selected_until_user_changes_it(controller, qtbot, monkeypatch):
    controller.settings.setValue("render/decoder", "cuda")
    controller.settings.setValue("render/scaler", "qsv")
    controller.settings.sync()
    monkeypatch.setattr(app, "render_hardware", lambda ffmpeg: (
        [("CPU", "none")], [("CPU", "cpu")],
    ))
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.decoder.currentText() == "NVIDIA NVDEC (unavailable)"
    assert restored.scaler.currentText() == "Intel Quick Sync (unavailable)"
    assert not restored.decoder.model().item(restored.decoder.currentIndex()).isEnabled()
    restored.quality.setValue(23)
    assert restored.render_config().decoder == "cuda"
    assert restored.render_config().scaler == "qsv"
    assert restored.settings.value("render/decoder") == "cuda"
    assert restored.settings.value("render/scaler") == "qsv"
    restored.decoder.setCurrentIndex(restored.decoder.findData("none"))
    restored.scaler.setCurrentIndex(restored.scaler.findData("cpu"))
    assert restored.render_config().decoder == "none"
    assert restored.render_config().scaler == "cpu"


@pytest.mark.parametrize("exit_action", [False, True])
def test_close_flushes_latest_active_state_before_window_closes(controller, tmp_path, qtbot, monkeypatch, exit_action):
    clips = [Clip(tmp_path / f"latest{i}.mp4", i + 1, 60, 120, True) for i in range(4)]
    controller.clips = clips
    controller.assembler.tracks = [[clips[2], clips[0]], [clips[3]], [clips[1]]]
    controller.quality.setValue(19)
    controller.project_name.setText("Latest name")
    controller.window.resize(1100, 800)
    visibility_at_save = []
    sync = controller.settings.sync

    def flush():
        visibility_at_save.append(controller.window.isVisible())
        sync()

    monkeypatch.setattr(controller.settings, "sync", flush)
    if exit_action:
        menu = controller.window.menuBar().actions()[0].menu()
        next(action for action in menu.actions() if action.text() == "Exit").trigger()
    else:
        assert controller.window.close()
    assert visibility_at_save == [True]
    assert not controller.window.isVisible()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.clips == clips
    assert restored.assembler.tracks == controller.assembler.tracks
    assert restored.quality.value() == 19
    assert restored.project_name.text() == "Latest name"
    assert restored.settings.value("mainWindow/geometry") == controller.window.saveGeometry()
    assert restored.settings.value("mainWindow/state") == controller.window.saveState(1)


def test_active_timeline_order_restores_after_each_edit(controller, tmp_path, qtbot, monkeypatch):
    monkeypatch.setattr(controller.preview, "set_clip", Mock())
    controller.clips = [Clip(tmp_path / f"order{i}.mp4", i + 1, 60, 120, True) for i in range(6)]
    controller.rebalance()
    controller.select_clip(controller.assembler.tracks[0][0])
    controller.move_selected_clips("forward")
    expected = [track[:] for track in controller.assembler.tracks]
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.tracks == expected
    assert not restored.loading
    assert restored.probing_paths == {}
    assert all(clip is next(source for source in restored.clips if source.path == clip.path)
               for track in restored.assembler.tracks for clip in track)

    controller.library.clearSelection()
    controller.select_clip(controller.assembler.tracks[1][0])
    controller.remove_selected_clip()
    removed = app.Application()
    qtbot.addWidget(removed.window)
    assert removed.assembler.tracks == controller.assembler.tracks
    assert sum(map(len, removed.assembler.tracks)) == 5

    controller.assembler.divisions.setValue(2)
    divided = app.Application()
    qtbot.addWidget(divided.window)
    assert divided.assembler.divisions.value() == 2
    assert divided.assembler.tracks == [[] for _ in range(6)]
    controller.rebalance(longest_first=True)
    ordered = app.Application()
    qtbot.addWidget(ordered.window)
    assert ordered.assembler.tracks == controller.assembler.tracks

    controller.clear()
    empty = app.Application()
    qtbot.addWidget(empty.window)
    assert empty.clips == []
    assert empty.assembler.tracks == [[] for _ in range(6)]


def test_interrupted_restore_retains_complete_saved_queue(controller, preview_source, tmp_path, qtbot, monkeypatch):
    second = tmp_path / 'second.mp4'
    second.hardlink_to(preview_source)
    controller.settings.setValue('sources/paths', [str(second), str(preview_source)])
    controller.settings.sync()
    monkeypatch.setattr(app.Application, 'probe_next', Mock())
    restored = app.Application(paths=[preview_source])
    qtbot.addWidget(restored.window)
    assert restored.pending == []
    assert not restored.loading
    restored.create_timelines()
    assert restored.pending == [second, preview_source]
    assert restored.settings.value('sources/paths', type=list) == [str(second), str(preview_source)]
    assert restored.assembler.tracks == [[], [], []]
    restored.loading = False


@pytest.mark.parametrize('normalization', ['None', 'True Peak', 'YouTube'])
@pytest.mark.parametrize('combine', [False, True])
def test_no_audio_omits_streams_and_measurements(controller, preview_source, tmp_path, qtbot, monkeypatch, normalization, combine):
    import json

    controller.normalization.setCurrentText(normalization)
    controller.combine.setChecked(combine)
    controller.audio_codec.setCurrentIndex(controller.audio_codec.findData('none'))
    assert not controller.normalization.isEnabled()
    assert controller.settings.value('audio/codec') == 'none'
    config = RenderConfig(column_width=60, height=120, encoder='libx264', speed='fast', normalization=normalization, audio_codec='none')
    monkeypatch.setattr(controller, 'render_config', lambda: config)
    controller.assembler.tracks = [[Clip(preview_source, 3, 60, 120, True)] for _ in range(3)]
    controller.start_export(tmp_path / 'silent.mp4')
    assert controller.measurement_keys == {}
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert controller.process.exitCode() == 0
    assert (tmp_path / 'silent_FINAL.mp4').exists() == combine
    for suffix in ['A', 'B', 'C'] + (['FINAL'] if combine else []):
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(tmp_path / f'silent_{suffix}.mp4')], capture_output=True, text=True, check=True)
        streams = json.loads(result.stdout)['streams']
        assert [stream['codec_type'] for stream in streams] == ['video']
    controller.audio_codec.setCurrentIndex(controller.audio_codec.findData('aac'))
    assert controller.normalization.isEnabled()
    assert controller.normalization.currentText() == normalization


def test_clear_all_sources_button(controller, preview_source, qtbot):
    assert not controller.clear_sources_button.isEnabled()
    controller.add_paths([preview_source])
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    controller.assembler.create_button.click()
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    controller.library.setCurrentRow(0)
    layout = controller.library_dock.widget().layout()
    assert layout.indexOf(controller.clear_sources_button) == layout.indexOf(controller.remove_sources_button) + 1
    controller.running = True
    controller.update_enabled()
    assert not controller.clear_sources_button.isEnabled()
    controller.running = False
    controller.update_enabled()
    controller.progress.setFormat("A - %p% - ETA 00:01:00")
    controller.progress.setValue(800)
    controller.window.statusBar().showMessage("Old render")
    controller.clear_sources_button.click()
    assert controller.library.count() == 0
    assert controller.clips == []
    assert controller.assembler.tracks == [[], [], []]
    assert controller.preview.player.source().isEmpty()
    assert controller.settings.value('sources/paths', type=list) == []
    assert not controller.clear_sources_button.isEnabled()
    assert controller.progress.value() == 0
    assert controller.progress.text() == "0%"
    assert controller.window.statusBar().currentMessage() == "Ready"
    assert preview_source.exists()


def test_no_audio_restores_and_remains_disabled_after_busy_state(controller, qtbot):
    controller.normalization.setCurrentText('True Peak')
    controller.audio_codec.setCurrentText('No Audio')
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.audio_codec.currentText() == 'No Audio'
    assert restored.normalization.currentText() == 'True Peak'
    assert not restored.normalization.isEnabled()
    restored.running = True
    restored.update_enabled()
    restored.running = False
    restored.update_enabled()
    assert not restored.normalization.isEnabled()
    restored.audio_codec.setCurrentText('AAC')
    assert restored.normalization.isEnabled()
    assert restored.normalization.currentText() == 'True Peak'


def test_final_checkbox_placement_and_busy_lock(controller):
    assert controller.combine.text() == 'Create final assembly'
    layout = controller.assembler.layout()
    options = layout.itemAt(layout.count() - 3).layout()
    assert options.itemAtPosition(0, 0).widget() is controller.combine
    assert options.itemAtPosition(0, 2).widget() is controller.assembler.columns
    assert options.itemAtPosition(0, 4).widget() is controller.assembler.divisions
    assert controller.assembler.isAncestorOf(controller.combine)
    assert not controller.render_panel.isAncestorOf(controller.combine)
    controller.combine.setChecked(False)
    assert controller.settings.value('render/combine', type=bool) is False
    controller.running = True
    controller.update_enabled()
    assert not controller.combine.isEnabled()
    controller.running = False
    controller.update_enabled()
    assert controller.combine.isEnabled()


def test_final_checkbox_preserves_editor_and_restores_setting(controller, tmp_path, qtbot, monkeypatch):
    monkeypatch.setattr(controller.preview, 'set_clip', Mock())
    clips = [Clip(tmp_path / f'{i}.mp4', 10, 60, 120) for i in range(6)]
    controller.clips = clips
    controller.rebalance()
    controller.library.setCurrentRow(0)
    controller.library.item(1).setSelected(True)
    view = controller.assembler.timeline.getViewBox()
    view.setXRange(2, 5, padding=0)
    before = view.viewRange()[0][:]
    item = controller.library.item(0)
    for checked in [False, True, False]:
        controller.combine.setChecked(checked)
        assert view.viewRange()[0] == before
        assert controller.library.item(0) is item
        assert len(controller.library.selectedItems()) == 2
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert not restored.combine.isChecked()
    assert restored.assembler.isAncestorOf(restored.combine)
    for label, letter in zip(restored.assembler.track_labels, 'ABC'):
        assert label.toPlainText().startswith(f'{letter} - ')
    restored.loading = True
    restored.update_enabled()
    assert not restored.combine.isEnabled()
    restored.loading = False


def test_filename_only_add_and_restore_do_not_start_probe(controller, tmp_path, qtbot, monkeypatch):
    from fastvideoassembly.assembly import Source

    paths = [tmp_path / f'not_scanned_{i}.mp4' for i in range(3)]
    for path in paths:
        path.touch()
    probe = Mock()
    monkeypatch.setattr(controller.probe, 'start', probe)
    controller.add_paths(paths[:2])
    controller.add_paths(paths[1:])
    probe.assert_not_called()
    assert controller.clips == [Source(path) for path in paths]
    assert controller.library.count() == 3
    assert not controller.loading
    assert not controller.assembler.balance_button.isEnabled()
    assert not controller.assembler.longest_button.isEnabled()
    controller.window.close()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert not restored.loading
    assert restored.probe.state() == app.QProcess.ProcessState.NotRunning
    assert restored.clips == [Source(path) for path in paths]
    assert restored.assembler.tracks == [[], [], []]


def test_divisions_balance_display_selection_and_settings(controller, tmp_path, qtbot, monkeypatch):
    from PySide6.QtWidgets import QListWidget

    from fastvideoassembly.assembly import timeline_name

    monkeypatch.setattr(controller.preview, 'set_clip', Mock())
    assert controller.assembler.divisions.value() == 1
    controller.clips = [Clip(tmp_path / f'{i}.mp4', i + 1, 60, 120) for i in range(18)]
    controller.assembler.divisions.setValue(2)
    assert len(controller.assembler.tracks) == 6
    assert not any(controller.assembler.tracks)
    controller.assembler.create_button.click()
    totals = [sum(c.duration for c in track) for track in controller.assembler.tracks]
    assert max(totals) - min(totals) <= 5
    assert not controller.assembler.findChildren(QListWidget)
    assert len(controller.assembler.dividers) == 1
    assert len(controller.assembler.track_labels) == 6
    assert [heading.toPlainText().split(' - ')[0] for heading in controller.assembler.track_labels] == list('ABCDEF')
    members = [set(track) for track in controller.assembler.tracks]
    controller.assembler.longest_button.click()
    assert [set(track) for track in controller.assembler.tracks] == members
    assert all([c.duration for c in track] == sorted([c.duration for c in track], reverse=True) for track in controller.assembler.tracks)
    _column, start, end, clip = next(bound for bound in controller.assembler.segment_bounds if bound[0] == 4)
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.scenePos.return_value = controller.assembler.timeline.getViewBox().mapViewToScene(QPointF((start + end) / 2, 1))
    controller.timeline_clicked(event)
    assert controller.selected_clip == clip
    assert controller.library.currentItem().data(Qt.ItemDataRole.UserRole) == clip
    controller.select_clip(controller.assembler.tracks[2][0])
    assert sum(map(len, controller.assembler.tracks)) == 18
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.divisions.value() == 2
    assert restored.assembler.tracks == controller.assembler.tracks
    restored.clear()
    assert len(restored.assembler.tracks) == 6
    assert [timeline_name(i) for i in [0, 25, 26, 27, 299]] == ['A', 'Z', 'AA', 'AB', 'KN']


@pytest.mark.parametrize('combine, render_timelines', [(False, True), (True, True), (True, False)])
@pytest.mark.parametrize('audio_codec', ['none', 'aac'])
@pytest.mark.parametrize('columns', [3, 4])
def test_two_divisions_render_independent_triples(controller, preview_source, tmp_path, qtbot, monkeypatch, combine, render_timelines, audio_codec, columns):
    import json

    controller.assembler.divisions.setValue(2)
    controller.assembler.columns.setCurrentText(str(columns))
    controller.combine.setChecked(combine)
    controller.assembler.render_timelines.setChecked(render_timelines)
    config = RenderConfig(column_width=60, height=120, encoder='libx264', speed='fast', normalization='True Peak', audio_codec=audio_codec)
    monkeypatch.setattr(controller, 'render_config', lambda: config)
    clips = []
    for i in range(columns * 2):
        path = tmp_path / f'source{i}.mp4'
        path.hardlink_to(preview_source)
        clips.append(Clip(path, 0.5 + i / 10, 60, 120, True))
    controller.assembler.tracks = [[clip] for clip in clips]
    letters = 'ABCDEFGH'[:columns * 2]
    first, second = letters[:columns], letters[columns:]
    first_final = tmp_path / f'division_FINAL_{first}.mp4'
    second_paths = {clip.path for clip in clips[columns:]}
    second_paths.update(tmp_path / f'division_{letter}.mp4' for letter in second)
    second_paths.add(tmp_path / f'division_FINAL_{second}.mp4')
    second_division_jobs = []
    start_job = controller.start_export_job

    def inspect_start():
        path, _, _ = controller.export_jobs[controller.export_index]
        if combine and path in second_paths:
            assert first_final.stat().st_size > 0
            second_division_jobs.append(path)
        start_job()

    monkeypatch.setattr(controller, 'start_export_job', inspect_start)
    controller.start_export(tmp_path / 'division.mp4')
    assert not controller.assembler.divisions.isEnabled()
    assert not controller.assembler.columns.isEnabled()
    expected_groups = (list(first) if render_timelines else []) + ([f'FINAL {first}'] if combine else []) + (list(second) if render_timelines else []) + ([f'FINAL {second}'] if combine else [])
    assert [group[0] for group in controller.export_groups] == expected_groups
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.process.exitCode() == 0
    assert bool(second_division_jobs) == combine
    outputs = (list(letters) if render_timelines else []) + ([f'FINAL_{first}', f'FINAL_{second}'] if combine else [])
    assert {p.stem for p in tmp_path.glob('division_*.mp4')} == {f'division_{suffix}' for suffix in outputs}
    for suffix in outputs:
        data = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(tmp_path / f'division_{suffix}.mp4')], capture_output=True, text=True, check=True).stdout)
        assert [stream['codec_type'] for stream in data['streams']] == (['video'] if audio_codec == 'none' else ['video', 'audio'])
        assert data['streams'][0]['width'] == (60 * columns if suffix.startswith('FINAL') else 60)
        if suffix.startswith('FINAL'):
            assert float(data['format']['duration']) == pytest.approx(0.5 + (columns - 1 if suffix.endswith(first) else columns * 2 - 1) / 10, abs=0.06)
    assert controller.assembler.divisions.isEnabled()
    assert controller.assembler.columns.isEnabled()


def test_four_columns_layout_and_persistence(controller, tmp_path, qtbot, monkeypatch):
    monkeypatch.setattr(controller.preview, "set_clip", Mock())
    assert [controller.assembler.columns.itemText(i) for i in range(controller.assembler.columns.count())] == ["3", "4"]
    assert controller.assembler.columns.currentData() == 3
    controller.assembler.divisions.setValue(2)
    controller.assembler.columns.setCurrentText("4")
    assert len(controller.assembler.tracks) == 8
    assert controller.render_config().column_width == 480
    controller.resolution.setCurrentIndex(1)
    assert controller.render_config().column_width == 960
    controller.clips = [Clip(tmp_path / f"four{i}.mp4", i + 1, 60, 120) for i in range(16)]
    controller.rebalance()
    assert len(controller.assembler.dividers) == 1
    assert len(controller.assembler.track_labels) == 8
    for column in range(8):
        _, start, end, clip = next(bound for bound in controller.assembler.segment_bounds if bound[0] == column)
        event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
        event.scenePos.return_value = controller.assembler.timeline.getViewBox().mapViewToScene(QPointF((start + end) / 2, 3 - column % 4))
        controller.timeline_clicked(event)
        assert controller.selected_clip == clip
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.columns.currentData() == 4
    assert restored.assembler.divisions.value() == 2
    assert restored.assembler.tracks == controller.assembler.tracks
    assert restored.render_config().column_width == 960
    restored.assembler.columns.setCurrentText("3")
    assert restored.assembler.tracks == [[] for _ in range(6)]
    assert restored.render_config().column_width == 1280


@pytest.mark.parametrize("columns, suffix", [(3, "DEF"), (4, "EFGH")])
def test_collision_in_later_division_blocks_entire_export(controller, tmp_path, monkeypatch, columns, suffix):
    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    controller.assembler.divisions.setValue(2)
    existing = tmp_path / f"assembly_FINAL_{suffix}.mp4"
    existing.touch()
    error = Mock()
    monkeypatch.setattr(app.QMessageBox, 'exec', lambda dialog: error(dialog))
    launch = Mock()
    monkeypatch.setattr(controller, 'start_export_job', launch)
    controller.start_export(tmp_path / 'assembly.mp4')
    launch.assert_not_called()
    assert str(existing) in error.call_args.args[0].text()


def test_remove_timelines_default_persistence_and_enabled_state(controller, qtbot):
    option = controller.assembler.remove_timelines
    assert not option.isChecked()
    assert option.isEnabled()
    option.setChecked(True)
    controller.combine.setChecked(False)
    assert not option.isEnabled()
    controller.combine.setChecked(True)
    assert option.isEnabled()
    controller.running = True
    controller.update_enabled()
    assert not option.isEnabled()
    controller.running = False
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.remove_timelines.isChecked()


@pytest.mark.parametrize('columns', [3, 4])
@pytest.mark.parametrize('outcome', ['success', 'failure', 'stopped'])
def test_final_cleanup_is_per_division_and_only_after_success(controller, preview_source, tmp_path, qtbot, monkeypatch, outcome, columns):
    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    first_letters = 'ABCDEFGH'[:columns]
    second_letters = 'ABCDEFGH'[columns:columns * 2]
    controller.assembler.divisions.setValue(2)
    controller.assembler.remove_timelines.setChecked(True)
    config = RenderConfig(column_width=60, height=120, encoder='libx264', speed='fast', normalization='True Peak')
    monkeypatch.setattr(controller, 'render_config', lambda: config)
    controller.assembler.tracks = [[Clip(preview_source, 0.5, 60, 120, True)] for _ in range(columns * 2)]
    first = tmp_path / f"cleanup_FINAL_{first_letters}.mp4"
    second = tmp_path / f"cleanup_FINAL_{second_letters}.mp4"
    start = controller.start_export_job
    checked = []

    def next_job():
        path, duration, _args = controller.export_jobs[controller.export_index]
        if path == second or path == first:
            letters = first_letters if path == first else second_letters
            assert all((tmp_path / f'cleanup_{letter}.mp4').exists() for letter in letters)
        if path == tmp_path / f"cleanup_{second_letters[0]}.mp4":
            assert first.exists()
            assert not any((tmp_path / f'cleanup_{letter}.mp4').exists() for letter in first_letters)
            checked.append('first complete')
        final_render = path == second and controller.export_index not in controller.measurement_keys
        if final_render and outcome == 'failure':
            controller.export_jobs[controller.export_index] = (path, duration, ['-invalid_cleanup_test_option'])
        start()
        if final_render and outcome == 'stopped':
            controller.stop_export()

    monkeypatch.setattr(controller, 'start_export_job', next_job)
    controller.start_export(tmp_path / 'cleanup.mp4')
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert checked == ['first complete']
    assert first.exists()
    assert not any((tmp_path / f'cleanup_{letter}.mp4').exists() for letter in first_letters)
    assert all((tmp_path / f'cleanup_{letter}.mp4').exists() for letter in second_letters) == (outcome != 'success')
    if outcome == 'success':
        assert second.exists()
        assert controller.process.exitCode() == 0
    assert preview_source.exists()


def test_columns_only_never_schedules_output_cleanup(controller, tmp_path, monkeypatch):
    controller.combine.setChecked(False)
    controller.assembler.remove_timelines.setChecked(True)
    controller.assembler.tracks = [[Clip(tmp_path / 'source.mp4', 1, 60, 120)] for _ in range(3)]
    monkeypatch.setattr(controller, 'start_export_job', Mock())
    controller.start_export(tmp_path / 'keep.mp4')
    assert all(path.parent != tmp_path for paths in controller.column_cleanup.values() for path in paths)
    controller.running = False
    controller.export_directory.cleanup()


@pytest.mark.parametrize("columns", [3, 4])
@pytest.mark.parametrize("division", [0, 1])
@pytest.mark.parametrize("source, drop, expected", [
    (2, 0.2, [0, 2, 1]),
    (2, 1.1, [0, 1, 2]),
    (0, 5.9, [1, 2, 0]),
    (1, 2.0, [0, 2, 1]),
])
def test_timeline_drag_snaps_and_preserves_duration(controller, tmp_path, qtbot, columns, division, source, drop, expected):
    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    controller.assembler.divisions.setValue(2)
    clips = [Clip(tmp_path / f"drag{i}.mp4", i + 1, 60, 120) for i in range(3)]
    other = Clip(tmp_path / "other.mp4", 8, 60, 120)
    column = division * columns + columns - 1
    controller.clips = [*clips, other]
    controller.assembler.tracks[0] = [other]
    controller.assembler.tracks[column] = clips.copy()
    controller.refresh()
    timeline = controller.assembler.timeline
    timeline.setXRange(0, 17, padding=0)
    view_range = timeline.getViewBox().viewRange()
    offset = controller.assembler.division_offsets[division]
    bar = next(bar for clip, bar in controller.assembler.segment_bars if clip == clips[source])
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.button.return_value = Qt.MouseButton.LeftButton
    event.isStart.return_value = True
    event.isFinish.return_value = False
    event.scenePos.return_value = timeline.getViewBox().mapViewToScene(QPointF(offset + drop, 0))
    bar.mouseDragEvent(event)
    assert bar.marker.isVisible()
    event.isStart.return_value = False
    event.isFinish.return_value = True
    bar.mouseDragEvent(event)
    assert controller.assembler.tracks[column] == [clips[i] for i in expected]
    assert controller.assembler.tracks[0] == [other]
    assert controller.selected_clip == clips[source]
    assert controller.library.currentItem().data(Qt.ItemDataRole.UserRole) == clips[source]
    bounds = [(start, end) for c, start, end, _ in controller.assembler.segment_bounds if c == column]
    assert bounds[0][0] == offset
    assert bounds[-1][1] - offset == pytest.approx(6)
    assert all(left[1] == right[0] for left, right in pairwise(bounds))
    assert timeline.getViewBox().viewRange() == view_range
    controller.save_active_state()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.tracks[column] == [clips[i] for i in expected]
    controller.rebalance()
    assert controller.assembler.tracks == balance(controller.clips, track_count=columns * 2)


@pytest.mark.parametrize("drop", [QPointF(1, 1), QPointF(-1, 2), QPointF(7, 2)])
def test_timeline_drag_outside_original_track_does_not_move(controller, tmp_path, drop):
    clips = [Clip(tmp_path / f"drag{i}.mp4", i + 1, 60, 120) for i in range(3)]
    controller.clips = clips
    controller.assembler.tracks[0] = clips.copy()
    controller.refresh()
    bar = controller.assembler.segment_bars[-1][1]
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.button.return_value = Qt.MouseButton.LeftButton
    event.isStart.return_value = True
    event.isFinish.return_value = True
    event.scenePos.return_value = controller.assembler.timeline.getViewBox().mapViewToScene(drop)
    bar.mouseDragEvent(event)
    assert controller.assembler.tracks[0] == clips
    assert bar.marker not in controller.assembler.timeline.items()


@pytest.mark.parametrize("columns", [3, 4])
def test_timeline_mouse_drag_and_click(controller, tmp_path, qtbot, columns):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    clips = [Clip(tmp_path / f"mouse{i}.mp4", 2, 60, 120) for i in range(3)]
    controller.clips = clips
    controller.assembler.tracks[-1] = clips.copy()
    controller.refresh()
    qtbot.wait(100)
    timeline = controller.assembler.timeline
    viewport = timeline.viewport()
    start = timeline.mapFromScene(timeline.getViewBox().mapViewToScene(QPointF(5, 0)))
    end = timeline.mapFromScene(timeline.getViewBox().mapViewToScene(QPointF(0.1, 0)))
    qtbot.mouseMove(viewport, start)
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(viewport.mapToGlobal(end)),
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.QApplication.sendEvent(viewport, move)
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    assert controller.assembler.tracks[-1] == [clips[0], clips[2], clips[1]]
    assert controller.selected_clip == clips[2]
    click = timeline.mapFromScene(timeline.getViewBox().mapViewToScene(QPointF(1, 0)))
    qtbot.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=click)
    assert controller.selected_clip == clips[0]


@pytest.mark.parametrize("busy", ["running", "loading"])
def test_timeline_drag_disabled_while_busy(controller, tmp_path, busy):
    clip = Clip(tmp_path / "busy.mp4", 2, 60, 120)
    controller.clips = [clip]
    controller.assembler.tracks[0] = [clip]
    controller.refresh()
    bar = controller.assembler.segment_bars[0][1]
    setattr(controller, busy, True)
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.button.return_value = Qt.MouseButton.LeftButton
    bar.hoverEvent(event)
    event.acceptDrags.assert_not_called()
    bar.mouseDragEvent(event)
    event.ignore.assert_called_once()
    setattr(controller, busy, False)


@pytest.mark.parametrize("columns", [3, 4])
def test_timeline_selection_and_scoped_sort(controller, tmp_path, qtbot, columns):
    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    controller.assembler.divisions.setValue(2)
    tracks = [[Clip(tmp_path / f"{c}-{i}.mp4", duration, 60, 120)
               for i, duration in enumerate([3, 1, 2])] for c in range(columns * 2)]
    controller.clips = [clip for track in tracks for clip in track]
    controller.assembler.tracks = [track[:] for track in tracks]
    controller.refresh()
    qtbot.wait(100)
    timeline = controller.assembler.timeline

    def click(column, x, y_offset=0.43):
        _, start, _, y = controller.assembler.track_bounds[column]
        position = timeline.mapFromScene(timeline.getViewBox().mapViewToScene(QPointF(start + x, y + y_offset)))
        qtbot.mouseClick(timeline.viewport(), Qt.MouseButton.LeftButton, pos=position)

    click(0, 1)
    assert controller.assembler.balance_button.text() == "Shortest First"
    assert controller.assembler.longest_button.text() == "Longest First"
    click(columns + 1, 1)
    assert controller.assembler.balance_button.text() == "Shortest First"
    assert controller.assembler.longest_button.text() == "Longest First"
    assert controller.assembler.selected_timelines == {0, columns + 1}
    assert controller.assembler.track_backgrounds[0].property("selected")
    assert controller.assembler.track_backgrounds[0].opts["brush"].alpha() == 28
    click(0, 1, 0)
    assert controller.selected_clip == tracks[0][0]
    assert controller.assembler.selected_timelines == {0, columns + 1}
    bar = controller.assembler.segment_bars[0][1]
    assert bar.property("active")
    assert bar.opts["brush"].alpha() == 255
    assert bar.opts["pen"].width() == 3
    controller.assembler.balance_button.click()
    for column, track in enumerate(controller.assembler.tracks):
        assert track == (sorted(tracks[column], key=lambda clip: clip.duration) if column in {0, columns + 1} else tracks[column])
    controller.assembler.longest_button.click()
    assert [clip.duration for clip in controller.assembler.tracks[0]] == [3, 2, 1]
    assert controller.assembler.tracks[1] == tracks[1]
    click(0, 1)
    assert controller.assembler.selected_timelines == {columns + 1}
    assert not controller.assembler.track_backgrounds[0].property("selected")
    assert controller.assembler.balance_button.text() == "Shortest First"
    assert controller.assembler.longest_button.text() == "Longest First"
    controller.select_clip(None)
    for _, bar in controller.assembler.segment_bars:
        assert not bar.property("active")
        assert bar.opts["brush"].alpha() == (190 if bar.index % 2 == 0 else 110)
        assert bar.opts["pen"].width() == 1
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=True))
    controller.timeline_clicked(event)
    assert controller.assembler.selected_timelines == {columns + 1}
    controller.apply_appearance()
    assert controller.assembler.track_backgrounds[columns + 1].property("selected")
    controller.assembler.columns.setCurrentIndex(1 if columns == 3 else 0)
    assert not controller.assembler.selected_timelines
    assert controller.assembler.balance_button.text() == "Shortest First"
    assert controller.assembler.longest_button.text() == "Longest First"


@pytest.mark.parametrize("action, expected", [
    (-1, [1, 2, 4, 0, 3]), (1, [0, 3, 1, 2, 4]),
    ("start", [1, 2, 4, 0, 3]), ("end", [0, 3, 1, 2, 4]),
])
def test_move_multiple_selected_clips(controller, tmp_path, qtbot, action, expected):
    tracks = [[Clip(tmp_path / f"{c}-{i}.mp4", i + 1, 60, 120) for i in range(5)] for c in range(3)]
    controller.clips = [clip for track in tracks for clip in track]
    controller.assembler.tracks = [track[:] for track in tracks]
    controller.refresh()
    for column in [0, 2]:
        for index in [1, 2, 4]:
            _, start, end, _clip = next(bound for bound in controller.assembler.segment_bounds
                                       if bound[0] == column and bound[3] == tracks[column][index])
            event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
            event.scenePos.return_value = controller.assembler.timeline.getViewBox().mapViewToScene(QPointF((start + end) / 2, 2 - column))
            controller.timeline_clicked(event)
    assert len(controller.library.selectedItems()) == 6
    controller.timeline_clicked(event)
    assert len(controller.library.selectedItems()) == 5
    assert controller.assembler.clips_group.title() == "Clips (5)"
    controller.timeline_clicked(event)
    assert len(controller.library.selectedItems()) == 6
    assert controller.assembler.clips_group.title() == "Clips (6)"
    assert controller.assembler.forward_button.text() == "Move Forward"
    assert controller.assembler.backward_button.text() == "Move Backward"
    assert controller.assembler.start_button.text() == "Move to Start"
    assert controller.assembler.end_button.text() == "Move to End"
    buttons = {-1: controller.assembler.backward_button, 1: controller.assembler.forward_button,
               "start": controller.assembler.start_button, "end": controller.assembler.end_button}
    buttons[action].click()
    assert controller.assembler.tracks[1] == tracks[1]
    for column in [0, 2]:
        assert controller.assembler.tracks[column] == [tracks[column][i] for i in expected]
    assert len(controller.library.selectedItems()) == 6
    assert sum(bar.property("active") for _, bar in controller.assembler.segment_bars) == 6
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.tracks == controller.assembler.tracks


@pytest.mark.parametrize("columns", [3, 4])
@pytest.mark.parametrize("drop, expected", [(0.1, [0, 1, 3, 2, 4]), (2.1, [0, 2, 4, 1, 3]), (4.9, [0, 2, 4, 1, 3])])
def test_drag_disjoint_selected_clips_as_block(controller, tmp_path, qtbot, columns, drop, expected):
    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    controller.assembler.divisions.setValue(2)
    column = columns * 2 - 1
    clips = [Clip(tmp_path / f"block{i}.mp4", 1, 60, 120) for i in range(5)]
    controller.clips = clips
    controller.assembler.tracks[column] = clips.copy()
    controller.refresh()
    controller.library.item(1).setSelected(True)
    controller.library.item(3).setSelected(True)
    bar = next(bar for clip, bar in controller.assembler.segment_bars if clip == clips[3])
    offset = controller.assembler.division_offsets[1]
    event = Mock(button=Mock(return_value=Qt.MouseButton.LeftButton), isAccepted=Mock(return_value=False))
    event.isStart.return_value = True
    event.isFinish.return_value = False
    event.scenePos.return_value = controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(offset + drop, 0))
    bar.mouseDragEvent(event)
    assert len(controller.library.selectedItems()) == 2
    event.isStart.return_value = False
    event.isFinish.return_value = True
    bar.mouseDragEvent(event)
    assert controller.assembler.tracks[column] == [clips[i] for i in expected]
    assert len(controller.library.selectedItems()) == 2
    assert sum(bar.property("active") for _, bar in controller.assembler.segment_bars) == 2
    bounds = [(start, end) for c, start, end, _ in controller.assembler.segment_bounds if c == column]
    assert bounds[-1][1] - bounds[0][0] == pytest.approx(5)
    assert all(left[1] == right[0] for left, right in pairwise(bounds))
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.tracks == controller.assembler.tracks


@pytest.mark.parametrize("index", [0, 2])
def test_clip_move_directions_at_timeline_ends(controller, tmp_path, index):
    clips = [Clip(tmp_path / f"direction{i}.mp4", 1, 60, 120) for i in range(3)]
    controller.clips = clips
    controller.assembler.tracks[0] = clips.copy()
    controller.refresh()
    controller.select_clip(clips[index])
    forward = controller.assembler.forward_button
    backward = controller.assembler.backward_button
    assert forward.text() == "Move Forward"
    assert backward.text() == "Move Backward"
    assert forward.isEnabled() == (index == 0)
    assert backward.isEnabled() == (index == 2)
    (forward if index == 0 else backward).click()
    assert controller.assembler.tracks[0].index(clips[index]) == 1
    assert forward.isEnabled()
    assert backward.isEnabled()


@pytest.mark.parametrize("columns", [3, 4])
@pytest.mark.parametrize("selection", [set(), {0}, {0, 2}])
def test_shuffle_within_target_timelines(controller, tmp_path, qtbot, monkeypatch, columns, selection):
    import random

    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    controller.assembler.divisions.setValue(2)
    tracks = [[Clip(tmp_path / f"shuffle{c}-{i}.mp4", i + 1, 60, 120) for i in range(5)] for c in range(columns * 2)]
    controller.clips = [clip for track in tracks for clip in track]
    controller.assembler.tracks = [track[:] for track in tracks]
    controller.assembler.selected_timelines = selection.copy()
    controller.refresh()
    controller.select_clip(tracks[0][0])
    view_range = controller.assembler.timeline.getViewBox().viewRange()
    shuffle = Mock(side_effect=random.Random(12).shuffle)
    monkeypatch.setattr(app.random, "shuffle", shuffle)
    controller.assembler.shuffle_button.click()
    targets = selection or set(range(columns * 2))
    assert shuffle.call_count == len(targets)
    for column, track in enumerate(controller.assembler.tracks):
        assert set(track) == set(tracks[column])
        assert sum(clip.duration for clip in track) == sum(clip.duration for clip in tracks[column])
        if column not in targets:
            assert track == tracks[column]
    assert any(controller.assembler.tracks[column] != tracks[column] for column in targets)
    assert controller.assembler.selected_timelines == selection
    assert controller.selected_clip == tracks[0][0]
    assert controller.assembler.timeline.getViewBox().viewRange() == view_range
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.assembler.tracks == controller.assembler.tracks
    controller.running = True
    controller.update_enabled()
    assert not controller.assembler.shuffle_button.isEnabled()
    controller.running = False


@pytest.mark.parametrize("columns", [3, 4])
@pytest.mark.parametrize("division", [0, 1])
@pytest.mark.parametrize("drop", [15.1, 39.9])
def test_real_drag_marker_matches_final_start_after_gap_closure(controller, tmp_path, qtbot, columns, division, drop):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent

    controller.assembler.columns.setCurrentIndex(controller.assembler.columns.findData(columns))
    controller.assembler.divisions.setValue(2)
    column = division * columns
    clips = [Clip(tmp_path / f"actual{i}.mp4", 10, 60, 120) for i in range(4)]
    controller.clips = clips
    controller.assembler.tracks[column] = clips.copy()
    controller.refresh()
    controller.select_clip(clips[0])
    controller.library.item(2).setSelected(True)
    qtbot.wait(100)
    timeline = controller.assembler.timeline
    viewport = timeline.viewport()
    offset = controller.assembler.division_offsets[division]
    y = columns - 1
    start = timeline.mapFromScene(timeline.getViewBox().mapViewToScene(QPointF(offset + 5, y)))
    end = timeline.mapFromScene(timeline.getViewBox().mapViewToScene(QPointF(offset + drop, y)))
    qtbot.mouseMove(viewport, start)
    qtbot.mousePress(viewport, Qt.MouseButton.LeftButton, pos=start)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(end), QPointF(viewport.mapToGlobal(end)),
                      Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    app.QApplication.sendEvent(viewport, move)
    bar = controller.assembler.segment_bars[0][1]
    assert bar.marker.isVisible()
    marker_x = bar.marker.getData()[0][0]
    assert marker_x == pytest.approx(offset + 20)
    qtbot.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=end)
    assert controller.assembler.tracks[column] == [clips[1], clips[3], clips[0], clips[2]]
    first_moved = next(bound for bound in controller.assembler.segment_bounds if bound[3] == clips[0])
    assert first_moved[1] == pytest.approx(marker_x)
    assert len(controller.library.selectedItems()) == 2
    assert not controller.assembler.selected_timelines
    assert bar.marker not in timeline.items()


def test_organize_all_never_redistributes_manual_timelines(controller, tmp_path):
    clips = [Clip(tmp_path / f"manual{i}.mp4", i + 1, 60, 120) for i in range(6)]
    controller.clips = clips
    controller.assembler.tracks = [[clips[5], clips[0], clips[3]], [clips[1]], [clips[4], clips[2]]]
    originals = [track[:] for track in controller.assembler.tracks]
    controller.refresh()
    for button, reverse in [(controller.assembler.balance_button, False), (controller.assembler.longest_button, True)]:
        button.click()
        for track, original in zip(controller.assembler.tracks, originals):
            assert track == sorted(original, key=lambda clip: clip.duration, reverse=reverse)
    controller.assembler.select_none_button.click()
    assert controller.assembler.clips_group.title() == "Clips (0)"


def test_interim_checkbox_persistence_and_output_selection(controller, tmp_path, qtbot):
    from fastvideoassembly.app import Application

    interim = controller.assembler.render_timelines
    assert interim.text() == "Render interim timelines"
    assert interim.isChecked()
    options = controller.assembler.layout().itemAt(controller.assembler.layout().count() - 3).layout()
    assert options.itemAtPosition(1, 0).widget() is interim
    assert options.itemAtPosition(2, 0).widget() is controller.assembler.remove_timelines
    controller.assembler.tracks = [[Clip(tmp_path / "source.mp4", 1, 60, 120)]] * 3
    controller.combine.setChecked(True)
    controller.assembler.remove_timelines.setChecked(True)
    interim.setChecked(False)
    assert not controller.assembler.remove_timelines.isEnabled()
    assert controller.assembler.export_button.isEnabled()
    controller.combine.setChecked(False)
    assert not controller.assembler.export_button.isEnabled()
    controller.combine.setChecked(True)
    restored = Application()
    qtbot.addWidget(restored.window)
    assert not restored.assembler.render_timelines.isChecked()
    controller.running = True
    controller.update_enabled()
    assert not interim.isEnabled()
    controller.running = False
    controller.update_enabled()
    assert interim.isEnabled()


@pytest.mark.parametrize("normalization", ["None", "YouTube", "True Peak"])
def test_direct_division_preserves_existing_interims(controller, preview_source, tmp_path, qtbot, monkeypatch, normalization):
    import json

    controller.assembler.render_timelines.setChecked(False)
    controller.assembler.remove_timelines.setChecked(True)
    controller.combine.setChecked(True)
    config = RenderConfig(column_width=60, height=120, encoder="libx264", normalization=normalization)
    monkeypatch.setattr(controller, "render_config", lambda: config)
    # Repeated sources share one measurement; the silent segment needs no source audio.
    audible = Clip(preview_source, 0.5, 60, 120, True)
    silent = Clip(preview_source, 0.2, 60, 120, False)
    controller.assembler.tracks = [[audible, silent, audible], [audible], [silent, audible]]
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
    data = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
        str(tmp_path / "direct_FINAL.mp4"),
    ], capture_output=True, text=True, check=True).stdout)
    assert [stream["codec_type"] for stream in data["streams"]] == ["video", "audio"]
    assert float(data["format"]["duration"]) == pytest.approx(1.2, abs=0.06)


@pytest.mark.parametrize("interims", [False, True])
def test_normalization_cache_survives_restart(controller, preview_source, tmp_path, qtbot, monkeypatch, interims):
    clip = Clip(preview_source, 0.5, 60, 120, True)
    controller.clips = [clip]
    controller.assembler.tracks = [[clip], [clip], [clip]]
    controller.assembler.render_timelines.setChecked(interims)
    controller.normalization.setCurrentText("True Peak")
    config = RenderConfig(column_width=60, height=120, encoder="libx264", normalization="True Peak")
    monkeypatch.setattr(controller, "render_config", lambda: config)
    controller.start_export(tmp_path / "first.mp4")
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert len(controller.normalization_cache) == 2
    peaks = dict(controller.audio_peaks)
    restored = app.Application()
    qtbot.addWidget(restored.window)
    monkeypatch.setattr(restored, "render_config", lambda: config)
    restored.start_export(tmp_path / "second.mp4")
    qtbot.waitUntil(lambda: not restored.running, timeout=30000)
    assert restored.measurement_keys == {}
    assert restored.audio_peaks[preview_source] == peaks[preview_source]
    assert (tmp_path / "second_FINAL.mp4").exists()
    restored.assembler.tracks[0].append(clip)
    restored.start_export(tmp_path / "edited.mp4")
    qtbot.waitUntil(lambda: not restored.running, timeout=30000)
    assert list(restored.measurement_keys.values()) == [tmp_path / "edited_FINAL.mp4"]


def test_manual_normalization_and_source_change(controller, preview_source, tmp_path, qtbot):
    clip = Clip(preview_source, 0.5, 60, 120, True)
    controller.clips = [clip]
    controller.normalization.setCurrentText("True Peak")
    controller.update_enabled()
    assert controller.normalize_button.isEnabled()
    controller.normalize_button.click()
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert len(controller.normalization_cache) == 1
    original_key = controller.source_audio_key(clip)
    controller.normalize_button.click()
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert list(controller.measurement_keys.values()) == [preview_source]
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.normalization_cache == controller.normalization_cache
    preview_source.touch()
    assert restored.source_audio_key(clip) != original_key
    controller.audio_codec.setCurrentIndex(controller.audio_codec.findData("none"))
    assert not controller.normalize_button.isEnabled()


@pytest.mark.parametrize("outcome", ["success", "stop", "failure"])
def test_manual_normalization_preserves_cache_until_success(controller, preview_source, qtbot, monkeypatch, outcome):
    import json

    clip = Clip(preview_source, 0.5, 60, 120, True)
    controller.clips = [clip]
    controller.normalization.setCurrentText("True Peak")
    source_key = json.dumps(["source-v1", controller.source_audio_key(clip)])
    mix_key = json.dumps(["mix-v1", "previous mix"])
    controller.normalization_cache = {source_key: "-6.0", mix_key: "-8.0"}
    controller.save_active_state()
    worker = Mock()
    worker.readAllStandardOutput.return_value = b""
    worker.readAllStandardError.return_value = b'{"input_tp": "-inf"}'
    monkeypatch.setattr(app, "QProcess", Mock(return_value=worker))
    controller.normalize_audio()
    assert controller.normalization_cache == {source_key: "-6.0", mix_key: "-8.0"}
    if outcome == "stop":
        controller.stop_export()
    controller.measurement_finished(worker, 1 if outcome == "failure" else 0, None)
    assert not controller.running
    expected = {source_key: "-inf"} if outcome == "success" else {source_key: "-6.0", mix_key: "-8.0"}
    assert controller.normalization_cache == expected
    assert json.loads(controller.settings.value("audio/measurements")) == expected


@pytest.mark.parametrize("change", ["unchanged", "file", "codec", "fps", "duration"])
def test_normalization_cache_invalidation(controller, preview_source, tmp_path, qtbot, monkeypatch, change):
    import os
    from dataclasses import replace

    clip = Clip(preview_source, 0.5, 60, 120, True)
    controller.clips = [clip]
    controller.assembler.tracks = [[clip], [clip], [clip]]
    controller.assembler.render_timelines.setChecked(False)
    config = RenderConfig(column_width=60, height=120, encoder="libx264", normalization="True Peak")
    monkeypatch.setattr(controller, "render_config", lambda: config)
    controller.start_export(tmp_path / "first.mp4")
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert len(controller.normalization_cache) == 2
    if change == "file":
        stat = preview_source.stat()
        os.utime(preview_source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    elif change == "codec":
        config = replace(config, audio_codec="ac3")
    elif change == "fps":
        config = replace(config, fps="60")
    elif change == "duration":
        clip = replace(clip, duration=0.7)
        controller.assembler.tracks = [[clip], [clip], [clip]]
    monkeypatch.setattr(controller, "start_export_job", Mock())
    controller.start_export(tmp_path / "second.mp4")
    expected = [] if change == "unchanged" else [tmp_path / "second_FINAL.mp4"]
    if change in ("file", "duration"):
        expected.insert(0, preview_source)
    assert list(controller.measurement_keys.values()) == expected
    controller.running = False
    controller.export_directory.cleanup()
    controller.export_directory = None
