import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPointF, Qt, QUrl
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


def test_progress_and_eta_span_timeline_jobs(controller, tmp_path, monkeypatch):
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
    clock[0] = 110
    process.readAllStandardOutput.return_value = b"out_time_us=50000000\n"
    controller.read_progress()
    assert controller.progress.value() == 250
    assert "ETA 00:00:30" in controller.progress.text()
    controller.export_index = 1
    controller.start_export_job()
    assert controller.progress.value() == 500
    clock[0] = 120
    controller.read_progress()
    assert controller.progress.value() == 750
    process.readAllStandardOutput.return_value = b"out_time_us=0\n"
    controller.read_progress()
    assert controller.progress.value() == 750
    for index, name in [(2, "B"), (4, "FINAL")]:
        controller.export_index = index
        controller.start_export_job()
        assert controller.progress.value() == 0
        assert controller.progress.text().startswith(name)
        assert "ETA --:--:--" in controller.progress.text()


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


def test_true_peak_measures_each_clip_immediately_before_rendering(
    controller, tmp_path, monkeypatch
):
    controller.normalization.setCurrentText("True Peak")
    controller.combine.setChecked(False)
    clips = [Clip(tmp_path / f"source{i}.mp4", 1, 90, 160, True) for i in range(4)]
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
    controller.assembler.tracks = [
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
    controller.assembler.tracks = [[clips[1]], [clips[0], clips[2]], [clips[3]]]
    controller.refresh()
    if origin == "source":
        controller.library.setCurrentRow(0)
    elif origin == "column":
        controller.assembler.lists[1].setCurrentRow(0)
    else:
        event = Mock()
        event.scenePos.return_value = (
            controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(1, 1))
        )
        controller.timeline_clicked(event)
    assert controller.selected_clip == clips[0]
    assert controller.library.currentRow() == 0
    assert [listing.currentRow() for listing in controller.assembler.lists] == [
        -1,
        0,
        -1,
    ]
    assert controller.assembler.active_column == 1
    assert controller.preview.player.source() == QUrl.fromLocalFile(str(preview_source))
    assert controller.assembler.down_button.isEnabled()
    assert controller.assembler.remove_button.isEnabled()
    controller.refresh()
    assert controller.selected_clip == clips[0]
    assert controller.assembler.lists[1].currentRow() == 0
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
    assert not controller.assembler.up_button.isEnabled()
    assert not controller.assembler.right_button.isEnabled()
    controller.assembler.remove_button.click()
    assert controller.clips == []
    assert preview_source.exists()


def test_import_counts_scanned_videos(
    controller, preview_source, qtbot
):
    controller.progress.setValue(1000)
    controller.add_paths([preview_source])
    assert controller.progress.value() == 0
    assert controller.progress.maximum() == 1
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert controller.progress.maximum() == 1
    assert controller.progress.value() == 1
    assert controller.progress.text() == "1 / 1 videos scanned"


def test_timeline_uses_rendered_frame_boundaries_and_ignores_gaps(controller, tmp_path):
    first = Clip(tmp_path / "first.mp4", 0.101, 60, 120)
    second = Clip(tmp_path / "second.mp4", 0.101, 60, 120)
    controller.clips = [first, second]
    controller.assembler.tracks = [[first, second], [], []]
    controller.refresh()
    assert controller.assembler.summary.text() == "Output Length: 00:00:00"
    assert controller.assembler.segment_bars[0][1].opts["width"] == pytest.approx(
        4 / 30
    )
    assert controller.assembler.segment_bars[1][1].opts["x0"] == pytest.approx(4 / 30)
    event = Mock()
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
    controller.assembler.lists[0].setCurrentRow(0)
    original = list(controller.assembler.tracks[0])
    controller.assembler.down_button.click()
    assert controller.assembler.tracks[0] == original[::-1]
    selected = controller.assembler.tracks[0][1]
    controller.assembler.right_button.click()
    assert controller.assembler.tracks[1][-1] == selected
    assert sum(map(len, controller.assembler.tracks)) == 6
    controller.clear()
    assert not controller.assembler.export_button.isEnabled()
    assert controller.library.count() == 0


def test_assembler_tab_and_shared_process_dock(controller):
    assert controller.window.centralWidget() is controller.assembler_tabs
    assert controller.assembler_tabs.count() == 1
    assert controller.assembler_tabs.tabText(0) == "3 Column Assembly"
    assert controller.assembler_tabs.widget(0) is controller.assembler
    for widget in (
        controller.assembler.timeline,
        controller.assembler.lists[0],
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
    assert "1280 × 2160" in controller.assembler.column_headers[0].text()
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

@pytest.mark.parametrize("origin", ["timeline", "column"])
def test_click_current_clip_replaces_source_multi_selection(controller, tmp_path, qtbot, monkeypatch, origin):
    monkeypatch.setattr(controller.preview, "set_clip", Mock())
    clips = [Clip(tmp_path / f"{i}.mp4", 3, 60, 120) for i in range(3)]
    controller.clips = clips[:]
    controller.assembler.tracks = [[clips[0]], [clips[1]], [clips[2]]]
    controller.refresh()
    library = controller.library
    library.setCurrentRow(0)
    library.item(1).setSelected(True)
    assert len(library.selectedItems()) == 2
    assert not controller.assembler.right_button.isEnabled()
    assert controller.assembler.remove_button.text() == "Remove Selected Clips"
    if origin == "timeline":
        event = Mock()
        event.scenePos.return_value = controller.assembler.timeline.getViewBox().mapViewToScene(QPointF(1, 2))
        controller.timeline_clicked(event)
    else:
        listing = controller.assembler.lists[0]
        qtbot.mouseClick(listing.viewport(), Qt.MouseButton.LeftButton,
                         pos=listing.visualItemRect(listing.item(0)).center())
    assert [library.row(item) for item in library.selectedItems()] == [0]
    assert controller.assembler.right_button.isEnabled()
    controller.assembler.remove_button.click()
    assert controller.clips == clips[1:]


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
    assert not controller.assembler.right_button.isEnabled()
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


def test_source_list_drop_adds_files_and_folders_incrementally(controller, preview_source, tmp_path, qtbot):
    from PySide6.QtCore import QMimeData, QPoint
    from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

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
        qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
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
    event = Mock()
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
    assert controller.open_action.text() == '&Add Videos…'
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
    tracks = [list(track) for track in controller.assembler.tracks]
    added = tmp_path / 'additional.mp4'
    added.hardlink_to(preview_source)
    controller.add_paths([added])
    qtbot.waitUntil(lambda: not controller.loading, timeout=15000)
    assert len(controller.clips) == 2
    assert controller.assembler.tracks == tracks
    controller.assembler.create_button.click()
    assert sum(map(len, controller.assembler.tracks)) == 2
    assert controller.assembler.export_button.text() == 'Render Column Assembly'
    controller.combine.setChecked(False)
    assert controller.assembler.export_button.text() == 'Render Column Assembly'
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


def test_interrupted_restore_retains_complete_saved_queue(controller, preview_source, tmp_path, qtbot, monkeypatch):
    second = tmp_path / 'second.mp4'
    second.hardlink_to(preview_source)
    controller.settings.setValue('sources/paths', [str(second), str(preview_source)])
    controller.settings.sync()
    monkeypatch.setattr(app.Application, 'probe_next', Mock())
    restored = app.Application(paths=[preview_source])
    qtbot.addWidget(restored.window)
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
    controller.library.setCurrentRow(0)
    layout = controller.library_dock.widget().layout()
    assert layout.indexOf(controller.clear_sources_button) == layout.indexOf(controller.remove_sources_button) + 1
    controller.running = True
    controller.update_enabled()
    assert not controller.clear_sources_button.isEnabled()
    controller.running = False
    controller.update_enabled()
    controller.progress.setFormat("A · %p% · ETA 00:01:00")
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
