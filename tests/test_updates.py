import json
import os
import subprocess
import sys
from concurrent.futures import Future
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
import requests
import shiboken6
from PySide6.QtWidgets import QMainWindow

from fastvideoassembly import app, updates


@pytest.fixture
def dialog(qtbot):
    controller = Mock(window=QMainWindow())
    qtbot.addWidget(controller.window)
    instance = updates.UpdateDialog(controller)
    qtbot.addWidget(instance)
    yield instance
    instance.reject()


@pytest.mark.parametrize("version,available", [("0.5.1", True), ("0.10.0", True), ("0.5.0", False), ("0.4.0", False)])
def test_release_comparison(dialog, monkeypatch, qtbot, version, available):
    monkeypatch.setattr(updates, "APP_VERSION", "0.5.0")
    asset = {"name": f"FastVideoAssembly-{version}-windows-amd64-Setup.exe"}
    monkeypatch.setattr(updates, "latest_release", lambda: {"tag_name": f"v{version}", "assets": [asset]})
    dialog.check_button.click()
    qtbot.waitUntil(lambda: not dialog.timer.isActive())
    assert dialog.download_button.isEnabled() == available
    assert not dialog.install_button.isEnabled()
    assert dialog.status.text() == (f"Version {version} available" if available else "Up to date")


def test_failed_check_surfaces_original_failure(dialog):
    dialog.operation = "check"
    dialog.future = Future()
    error = requests.HTTPError("403 Forbidden")
    dialog.future.set_exception(error)
    with pytest.raises(requests.HTTPError) as raised:
        dialog.completed()
    assert raised.value is error
    assert not dialog.download_button.isEnabled()
    assert not dialog.install_button.isEnabled()


@pytest.mark.parametrize("cancel", [False, True])
def test_download_completion_and_cancellation(tmp_path, monkeypatch, cancel):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [b"first", b"second"]
    monkeypatch.setattr(updates.requests, "get", Mock(return_value=response))
    cancelled = Event()
    progress = Mock(side_effect=lambda *args: cancelled.set() if cancel else None)
    asset = {"name": "Setup.exe", "size": 11, "browser_download_url": "https://example.test/Setup.exe"}
    result = updates.download_installer(asset, tmp_path, cancelled, progress)
    assert not (tmp_path / "Setup.part").exists()
    if cancel:
        assert result is None
        assert not (tmp_path / "Setup.exe").exists()
    else:
        assert result.read_bytes() == b"firstsecond"
        assert progress.call_args.args == (11, 11)


def test_interrupted_download_never_becomes_installer(tmp_path, monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)

    def interrupted(size):
        yield b"partial"
        raise requests.exceptions.ChunkedEncodingError("IncompleteRead")

    response.iter_content.side_effect = interrupted
    monkeypatch.setattr(updates.requests, "get", Mock(return_value=response))
    asset = {"name": "Setup.exe", "size": 100, "browser_download_url": "https://example.test/Setup.exe"}
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        updates.download_installer(asset, tmp_path, Event(), Mock())
    assert not (tmp_path / "Setup.exe").exists()


def test_download_enables_install_only_after_completion(dialog, monkeypatch, tmp_path, qtbot):
    done = Event()
    monkeypatch.setattr(updates, "user_cache_path", lambda *args, **kwargs: tmp_path)

    def download(asset, directory, cancelled, progress):
        progress(5, 10)
        done.wait(5)
        return directory / "Setup.exe"

    monkeypatch.setattr(updates, "download_installer", download)
    dialog.asset = {"size": 10}
    dialog.download()
    qtbot.waitUntil(lambda: dialog.progress.value() == 50)
    assert not dialog.install_button.isEnabled()
    done.set()
    qtbot.waitUntil(lambda: dialog.install_button.isEnabled())
    assert dialog.progress.value() == 100
    helper = Mock()
    monkeypatch.setattr(updates, "install_after_exit", helper)
    dialog.cancel_button.click()
    helper.assert_not_called()
    assert dialog.cancelled.is_set()


def test_cancelled_download_can_finish_after_dialog_deleted(monkeypatch, tmp_path, qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)
    instance = updates.UpdateDialog(Mock(window=window))
    started = Event()
    finish = Event()
    monkeypatch.setattr(updates, "user_cache_path", lambda *args, **kwargs: tmp_path)

    def download(asset, directory, cancelled, progress):
        started.set()
        finish.wait(5)
        progress(5, 10)
        assert cancelled.is_set()

    monkeypatch.setattr(updates, "download_installer", download)
    instance.asset = {"size": 10}
    instance.download()
    qtbot.waitUntil(started.is_set)
    instance.reject()
    shiboken6.delete(instance)
    finish.set()
    assert instance.future.result(timeout=5) is None


@pytest.mark.parametrize("accepted", [False, True])
def test_install_respects_close_result(dialog, monkeypatch, tmp_path, accepted):
    events = []
    dialog.controller.window.close = Mock(side_effect=lambda: events.append("close") or accepted)
    dialog.installer = tmp_path / "Setup.exe"
    helper = Mock(side_effect=lambda path: events.append("helper"))
    monkeypatch.setattr(updates, "install_after_exit", helper)
    application = Mock()
    application.instance.return_value.quit.side_effect = lambda: events.append("quit")
    monkeypatch.setattr(updates, "QApplication", application)
    dialog.install()
    assert events == (["close", "helper", "quit"] if accepted else ["close"])


def test_installer_waits_for_actual_parent_exit(tmp_path, qtbot):
    # A harmless GUI executable records when it starts; no real Setup is run.
    marker = tmp_path / "started.txt"
    source = tmp_path / "installer.cs"
    source.write_text('class Installer { static void Main() { System.IO.File.WriteAllText(@"'
                      + str(marker) + '", "started"); } }')
    installer = tmp_path / "Test Setup.exe"
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    subprocess.run([str(compiler), "/nologo", "/target:winexe", f"/out:{installer}", str(source)], check=True)
    script = (
        "from pathlib import Path; from fastvideoassembly.updates import install_after_exit; "
        f"helper = install_after_exit(Path({str(installer)!r})); "
        "print(helper.pid, flush=True); input()"
    )
    parent = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    helper_pid = int(parent.stdout.readline())
    import _winapi
    helper_handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, helper_pid)
    qtbot.wait(1500)
    assert not marker.exists()
    parent.communicate("exit\n", timeout=10)
    assert parent.returncode == 0
    qtbot.waitUntil(marker.exists, timeout=30000)
    assert _winapi.WaitForSingleObject(helper_handle, 10000) == 0
    _winapi.CloseHandle(helper_handle)


def test_github_release_endpoint(monkeypatch):
    response = Mock()
    response.json.return_value = json.loads('{"tag_name": "v0.5.0"}')
    get = Mock(return_value=response)
    monkeypatch.setattr(updates.requests, "get", get)
    assert updates.latest_release() == {"tag_name": "v0.5.0"}
    get.assert_called_once_with(updates.RELEASE_URL, timeout=30)
    response.raise_for_status.assert_called_once()


def test_help_updates_disabled_during_work(qtbot):
    controller = app.Application(no_profile=True)
    qtbot.addWidget(controller.window)
    help_menu = next(action.menu() for action in controller.window.menuBar().actions() if action.text() == "&Help")
    assert controller.update_action in help_menu.actions()
    assert controller.update_action.text() == "Check for Updates..."
    assert controller.update_action.isEnabled()
    controller.loading = True
    controller.update_enabled()
    assert not controller.update_action.isEnabled()
    controller.loading = False
    controller.running = True
    controller.update_enabled()
    assert not controller.update_action.isEnabled()
    controller.running = False
    controller.update_enabled()
    assert controller.update_action.isEnabled()
    controller.window.close()
