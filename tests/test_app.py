from pathlib import Path
from unittest.mock import Mock

import pytest

from fastvideoassembly import app
from fastvideoassembly.assembly import Clip


@pytest.mark.parametrize("suffix", ["", "_A", "_B", "_C"])
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
    output.write_bytes(b"existing final")
    controller.combine.setChecked(False)
    controller.clips = [Clip(tmp_path / f"{i}.mp4", 1, 90, 160) for i in range(3)]
    controller.rebalance()
    launch = Mock()
    monkeypatch.setattr(controller, "start_export_job", launch)
    controller.start_export(output)
    launch.assert_called_once()
    assert len(controller.export_jobs) == 6
    assert output.read_bytes() == b"existing final"
    controller.running = False
    controller.export_directory.cleanup()


@pytest.fixture
def controller(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "user_config_path", lambda *args, **kwargs: tmp_path)
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.window.show()
    return controller


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
    assert not controller.mixed_button.isEnabled()
    assert controller.stop_button.isEnabled()
    controller.running = False


def test_order_buttons_keep_equal_track_totals(controller):
    assert controller.balance_button.text() == "Shortest to Longest"
    assert controller.mixed_button.text() == "Balanced"
    assert not controller.mixed_button.isEnabled()
    controller.clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 19)]
    controller.rebalance()
    original = [list(track) for track in controller.tracks]
    controller.mixed_button.click()
    assert controller.tracks != original
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
    assert "3840 × 2160" in controller.output_info.text()
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
