from pathlib import Path

import pytest

from fastvideoassembly import app
from fastvideoassembly.assembly import Clip


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
    assert controller.stop_button.isEnabled()
    controller.running = False
