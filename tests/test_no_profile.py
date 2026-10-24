import json
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QSettings, Qt

from fastvideoassembly import app, installed


def test_shared_test_defaults_skip_settings_and_window_activation(qtbot, monkeypatch, tmp_path):
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


@pytest.mark.profile
def test_profile_tests_stay_minimized_and_use_temporary_settings(qtbot, tmp_path):
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.window.show()
    assert controller.window.isMinimized()
    assert controller.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert not controller.window.isActiveWindow()
    assert controller.settings.fileName() == (tmp_path / "settings.ini").as_posix()
    controller.project_name.setText("Isolated persistence test")
    controller.window.close()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.project_name.text() == "Isolated persistence test"
    restored.window.close()


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
    assert first.settings.value("output/project", "") == ""
    first.project_name.setText("Temporary project")
    first.assembler.columns.setCurrentIndex(first.assembler.columns.findData(4))
    first.settings.sync()
    assert first.settings.value("output/project", "") == ""
    assert not first.settings.contains("assembly/columns")
    assert first.settings.beginReadArray("sources/scanned") == 0
    first.window.close()

    second = app.Application(no_profile=True)
    qtbot.addWidget(second.window)
    assert second.project_name.text() == ""
    assert second.assembler.columns.currentData() == 3
    second.window.close()

    if saved_profile:
        assert profile_path.read_bytes() == original
        normal = app.Application(no_profile=False)
        qtbot.addWidget(normal.window)
        assert normal.project_name.text() == "Saved project"
        assert normal.assembler.columns.currentData() == 4
        assert [clip.path for clip in normal.clips] == [tmp_path / "saved.mp4"]
        normal.window.close()
    else:
        assert not profile_path.exists()


@pytest.mark.parametrize("launcher", [app, installed])
@pytest.mark.parametrize("arguments", [
    [], ["-NoProfile"], ["-Minimize"], ["-NoProfile", "-Minimize"],
    ["first.mp4", "-Minimize", "-NoProfile", "second.mp4"],
])
def test_launchers_consume_no_profile_flag(monkeypatch, launcher, arguments):
    monkeypatch.setattr(launcher.sys, "argv", ["fastvideoassembly", *arguments])
    application = Mock()
    qt_application = Mock()
    qt_application.return_value.exec.return_value = 0
    monkeypatch.setattr(launcher, "Application", application)
    monkeypatch.setattr(launcher, "QApplication", qt_application)

    assert launcher.main() == 0
    assert application.call_args.kwargs["no_profile"] == ("-NoProfile" in arguments)
    assert application.call_args.kwargs["paths"] == [arg for arg in arguments if arg not in ("-NoProfile", "-Minimize")]
    assert application.call_args.kwargs["minimize"] == ("-Minimize" in arguments)
    application.return_value.window.show.assert_called_once()


@pytest.mark.parametrize("minimize", [False, True])
def test_window_starts_minimized_without_activation(qtbot, minimize):
    controller = app.Application(no_profile=True, minimize=minimize)
    qtbot.addWidget(controller.window)
    if minimize:
        controller.window.show()
    assert controller.window.isMinimized() is minimize
    assert controller.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is minimize
    controller.window.close()


def test_no_profile_never_opens_settings(qtbot, monkeypatch, tmp_path):
    settings = Mock()
    monkeypatch.setattr(app, "QSettings", settings)
    controller = app.Application(no_profile=True, minimize=True)
    qtbot.addWidget(controller.window)
    controller.window.show()
    controller.project_name.setText("Unsaved")
    controller.save_active_state()
    controller.window.close()
    settings.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_minimize_takes_precedence_over_saved_window_state(qtbot):
    previous = app.Application(no_profile=False, minimize=False)
    qtbot.addWidget(previous.window)
    previous.window.setWindowState(Qt.WindowState.WindowMaximized)
    previous.project_name.setText("Saved project")
    previous.window.close()

    restored = app.Application(no_profile=False, minimize=True)
    qtbot.addWidget(restored.window)
    restored.window.show()
    assert restored.window.isMinimized()
    assert restored.project_name.text() == "Saved project"
    restored.window.close()


@pytest.mark.parametrize("module", ["app", "installed"])
def test_minimized_no_profile_launch_end_to_end(tmp_path, module):
    if module == "installed":
        tools = tmp_path / "tools/ffmpeg/ffmpeg-8.1.2-essentials_build/bin"
        tools.mkdir(parents=True)
        shutil.copy2(shutil.which("ffmpeg"), tools / "ffmpeg.exe")
        shutil.copy2(shutil.which("ffprobe"), tools / "ffprobe.exe")
    script = '''
import json
import sys
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QMainWindow
from fastvideoassembly import app, installed

launcher = {"app": app, "installed": installed}[sys.argv.pop(1)]
profile = Path(sys.argv.pop(1))
app.user_config_path = lambda *args, **kwargs: profile
sys.prefix = str(profile.parent / "runtime/python")

class TestApplication(QApplication):
    def exec(self):
        def inspect():
            window = next(w for w in self.topLevelWidgets() if isinstance(w, QMainWindow))
            print(json.dumps({
                "minimized": window.isMinimized(),
                "show_without_activating": window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating),
                "active": window.isActiveWindow(),
            }), flush=True)
            window.close()
            self.quit()
        QTimer.singleShot(100, inspect)
        return super().exec()

launcher.QApplication = TestApplication
raise SystemExit(launcher.main())
'''
    result = subprocess.run(
        [sys.executable, "-c", script, module, str(tmp_path / "profile"), "-NoProfile", "-Minimize"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    assert json.loads(result.stdout) == {
        "minimized": True, "show_without_activating": True, "active": False,
    }
    assert not (tmp_path / "profile").exists()
