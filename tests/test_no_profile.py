from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSettings

from fastvideoassembly import app, installed


@pytest.mark.parametrize("saved_profile", [False, True])
def test_no_profile_leaves_user_settings_untouched(qtbot, tmp_path, monkeypatch, saved_profile):
    monkeypatch.setattr(app, "user_config_path", lambda *args, **kwargs: tmp_path)
    profile_path = tmp_path / "settings.ini"
    if saved_profile:
        saved = QSettings(str(profile_path), QSettings.Format.IniFormat)
        saved.setValue("output/project", "Saved project")
        saved.setValue("assembly/columns", 4)
        saved.setValue("render/column_width", 480)
        saved.setValue("sources/paths", [str(tmp_path / "saved.mp4")])
        saved.sync()
        original = profile_path.read_bytes()

    first = app.Application(no_profile=True)
    qtbot.addWidget(first.window)
    assert first.project_name.text() == ""
    assert first.assembler.columns.currentData() == 3
    assert first.clips == []
    assert Path(first.settings.fileName()).parent != tmp_path
    first.project_name.setText("Temporary project")
    first.assembler.columns.setCurrentIndex(first.assembler.columns.findData(4))
    first.settings.sync()
    first.window.close()

    second = app.Application(no_profile=True)
    qtbot.addWidget(second.window)
    assert second.settings.fileName() != first.settings.fileName()
    assert second.project_name.text() == ""
    assert second.assembler.columns.currentData() == 3
    second.window.close()

    if saved_profile:
        assert profile_path.read_bytes() == original
        normal = app.Application()
        qtbot.addWidget(normal.window)
        assert normal.project_name.text() == "Saved project"
        assert normal.assembler.columns.currentData() == 4
        assert [clip.path for clip in normal.clips] == [tmp_path / "saved.mp4"]
        normal.window.close()
    else:
        assert not profile_path.exists()


@pytest.mark.parametrize("launcher", [app, installed])
@pytest.mark.parametrize("arguments", [[], ["-NoProfile"], ["first.mp4", "-NoProfile", "second.mp4"]])
def test_launchers_consume_no_profile_flag(monkeypatch, launcher, arguments):
    monkeypatch.setattr(launcher.sys, "argv", ["fastvideoassembly", *arguments])
    application = Mock()
    qt_application = Mock()
    qt_application.return_value.exec.return_value = 0
    monkeypatch.setattr(launcher, "Application", application)
    monkeypatch.setattr(launcher, "QApplication", qt_application)

    assert launcher.main() == 0
    assert application.call_args.kwargs["no_profile"] == ("-NoProfile" in arguments)
    assert application.call_args.kwargs["paths"] == [arg for arg in arguments if arg != "-NoProfile"]
    application.return_value.window.show.assert_called_once()
