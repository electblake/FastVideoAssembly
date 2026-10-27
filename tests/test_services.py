import io
import json
import subprocess
import sys
from concurrent.futures import Future
from threading import Barrier, Event, get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from PySide6.QtWidgets import QMainWindow

from fastvideoassembly import classification, hardware, music_runtime, updates
from fastvideoassembly.assembly import Clip


def test_classification_routing_cache_and_failures(
    controller, preview_source, monkeypatch, qtbot
):
    with monkeypatch.context() as patch:
        clip = Clip(preview_source, 3, 60, 120, True)
        controller.clips = [clip]
        controller.refresh()
        controller.select_clip(clip)
        controller.music_device.setCurrentIndex(1)
        controller.music_gpu_index.setValue(2)
        controller.music_threads.setValue(8)
        requests, launches = [], []
        start = controller.classification_process.start
        write = controller.classification_process.write

        def worker(program, args):
            launches.append((program, args))
            start(
                sys.executable,
                [
                    "-c",
                    (
                        "import sys,json; r=json.load(sys.stdin); "
                        "[print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))),flush=True) for c in r['clips']]"
                    ),
                ],
            )

        def send(data):
            requests.append(json.loads(data))
            return write(data)

        patch.setattr(controller.classification_process, "start", worker)
        patch.setattr(controller.classification_process, "write", send)
        controller.classify_music()
        qtbot.waitUntil(lambda: not controller.running)
        assert launches[0][1] == ["-m", "fastvideoassembly.music_runtime", "classify"]
        assert requests[0]["device"] == "cuda"
        assert requests[0]["gpu_index"] == 2
        assert requests[0]["threads"] == 1
        assert requests[0]["cache_dir"] == str(music_runtime.model_cache_path())
        controller.classify_music()
        qtbot.waitUntil(lambda: not controller.running)
        assert len(launches) == 1
        controller.music_threshold.setValue(0.9)
        controller.apply_music_threshold_button.click()
        assert not controller.audio_muted
        controller.music_precision.setCurrentIndex(1)
        controller.music_gpu_threads.setValue(2)
        controller.classify_music()
        qtbot.waitUntil(lambda: not controller.running)
        assert requests[-1]["precision"] == "float32"
        assert requests[-1]["threads"] == 2
        controller.music_device.setCurrentIndex(0)
        controller.classify_music()
        qtbot.waitUntil(lambda: not controller.running)
        assert launches[-1][1] == ["-m", "fastvideoassembly.classification"]
        assert requests[-1]["threads"] == 8
        assert len(controller.classification_cache) == 3

    controller.classification_cache.clear()
    controller.audio_muted.clear()
    with monkeypatch.context() as patch:
        clip = Clip(preview_source, 3, 60, 120, True)
        controller.clips = [clip]
        controller.refresh()
        controller.select_clip(clip)
        controller.music_device.setCurrentIndex(1)
        start = controller.classification_process.start
        error = (
            "error: uv trampoline failed to spawn Python child process\n"
            "  Caused by: entity not found (os error 2)\n"
        )

        def launch(program, args):
            start(
                sys.executable,
                [
                    "-c",
                    (
                        "import sys,json; json.load(sys.stdin); "
                        f"sys.stderr.write({error!r}); sys.exit(1)"
                    ),
                ],
            )

        patch.setattr(controller.classification_process, "start", launch)
        controller.classify_music()
        qtbot.waitUntil(lambda: not controller.running)
        message = "GPU runtime could not start. Click Install GPU Dependencies in Audio Classification."
        assert error.strip() in controller.log.toPlainText()
        assert message in controller.log.toPlainText()
        assert controller.window.statusBar().currentMessage() == message
        assert controller.progress.format() == "Audio Classification failed - %v / %m"
        assert not controller.classification_timer.isActive()
        assert controller.music_panel.isEnabled()
        assert controller.install_music_dependencies.isEnabled()
        assert not controller.classification_cache
        assert not controller.audio_muted

        patch.setattr(
            controller.classification_process,
            "start",
            lambda program, args: start(
                sys.executable,
                [
                    "-c",
                    (
                        "import sys,json; r=json.load(sys.stdin); "
                        "[print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))),flush=True) for c in r['clips']]"
                    ),
                ],
            ),
        )
        controller.classify_music()
        qtbot.waitUntil(lambda: not controller.running)
        assert controller.classification_error == ""
        assert (
            controller.window.statusBar().currentMessage()
            == "Audio Classification complete"
        )

    for device, error in [
        ("cuda", "RuntimeError: CUDA out of memory"),
        (
            "cpu",
            "uv trampoline failed to spawn Python child process\nentity not found (os error 2)",
        ),
    ]:
        controller.music_device.setCurrentIndex(
            controller.music_device.findData(device)
        )
        controller.classification_buffer = ""
        controller.classification_error = error
        controller.classification_started = 0
        controller.classification_scanned = 0
        controller.classification_completed = 0
        controller.stop_requested = False
        previous_log = controller.log.toPlainText()
        with pytest.raises(subprocess.CalledProcessError):
            controller.classification_finished(
                1, controller.classification_process.exitStatus()
            )
        assert (
            "Click Install GPU Dependencies"
            not in controller.log.toPlainText()[len(previous_log) :]
        )


def test_worker_threads_own_and_reuse_classifiers(monkeypatch, capsys):
    threads = 2
    barrier = Barrier(threads)
    classifiers = []
    request = {
        "threads": threads,
        "ffmpeg": "ffmpeg",
        "labels": {"music": "music", "talking": "talking"},
        "device": "cpu",
        "precision": "float16",
        "gpu_index": 0,
        "cache_dir": "models",
        "clips": [
            {"key": str(index), "path": str(index), "duration": 1} for index in range(4)
        ],
    }

    def create(device, precision, gpu_index, cache_dir):
        assert (device, precision, gpu_index, cache_dir) == (
            "cpu",
            "float16",
            0,
            "models",
        )
        classifier = {"owner": get_ident(), "calls": 0}
        classifiers.append(classifier)
        return classifier

    def classify(classifier, ffmpeg, path, duration, labels):
        assert labels == {"music": "music", "talking": "talking"}
        assert classifier["owner"] == get_ident()
        classifier["calls"] += 1
        barrier.wait(timeout=10)
        return {"music": int(path) / 10, "talking": 0.1}

    monkeypatch.setattr(classification, "create_classifier", create)
    monkeypatch.setattr(classification, "classify_clip", classify)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request)))
    classification.main()
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(classifiers) == threads
    assert all(classifier["calls"] == 4 // threads for classifier in classifiers)
    assert sorted(results, key=lambda result: result["key"]) == [
        {
            "key": str(index),
            "path": str(index),
            "score": {"music": index / 10, "talking": 0.1},
        }
        for index in range(4)
    ]


def test_gpu_install_commands_and_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(music_runtime, "gpu_runtime_path", lambda: tmp_path / "gpu")
    run = Mock()
    monkeypatch.setattr(music_runtime.subprocess, "run", run)
    music_runtime.install_gpu_dependencies()
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0][-1] == str(tmp_path / "gpu")
    assert commands[1][commands[1].index("--python") + 1] == str(
        tmp_path / "gpu/Scripts/python.exe"
    )
    assert commands[1][commands[1].index("--torch-backend") + 1] == "cu130"
    assert all(call.kwargs["check"] for call in run.call_args_list)

    failure = subprocess.CalledProcessError(1, "uv")
    run = Mock(side_effect=failure)
    monkeypatch.setattr(music_runtime.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        music_runtime.install_gpu_dependencies()
    assert raised.value is failure
    assert run.call_count == 1


def test_hardware_capability_selection(monkeypatch):
    run = Mock(
        side_effect=[
            SimpleNamespace(stdout=json.dumps(["NVIDIA", "Intel Corporation"])),
            SimpleNamespace(stdout="cuda qsv d3d11va dxva2"),
            SimpleNamespace(stdout="scale_cuda scale_qsv vpp_qsv"),
        ]
    )
    monkeypatch.setattr(hardware.subprocess, "run", run)
    decoders, scalers = hardware.render_hardware("test-supported-ffmpeg")
    assert [value for _, value in decoders] == [
        "none",
        "cuda",
        "qsv",
        "d3d11va",
        "dxva2",
    ]
    assert [value for _, value in scalers] == ["cpu", "cuda", "qsv"]

    run = Mock(
        side_effect=[
            SimpleNamespace(stdout=json.dumps(["Intel Corporation"])),
            SimpleNamespace(stdout="cuda qsv d3d11va dxva2"),
            SimpleNamespace(stdout="scale_cuda vpp_qsv"),
        ]
    )
    monkeypatch.setattr(hardware.subprocess, "run", run)
    decoders, scalers = hardware.render_hardware("test-limited-ffmpeg")
    assert [value for _, value in decoders] == ["none", "qsv", "d3d11va", "dxva2"]
    assert scalers == [("CPU", "cpu")]


@pytest.fixture
def dialog(qtbot):
    controller = Mock(window=QMainWindow())
    qtbot.addWidget(controller.window)
    instance = updates.UpdateDialog(controller)
    qtbot.addWidget(instance)
    yield instance
    instance.reject()


def test_update_check_download_and_install_workflow(
    dialog, monkeypatch, tmp_path, qtbot
):
    monkeypatch.setattr(updates, "APP_VERSION", "0.5.0")
    release = {
        "tag_name": "v0.6.0",
        "assets": [{"name": "FastVideoAssembly-0.6.0-windows-amd64-Setup.exe"}],
    }
    monkeypatch.setattr(updates, "latest_release", lambda: release)
    dialog.check_button.click()
    qtbot.waitUntil(lambda: not dialog.timer.isActive())
    assert dialog.download_button.isEnabled()
    dialog.installer = tmp_path / "old-Setup.exe"
    dialog.install_button.setEnabled(True)
    dialog.progress.setValue(100)
    release = {"tag_name": "v0.5.0", "assets": []}
    dialog.check_button.click()
    assert not dialog.check_button.isEnabled()
    assert not dialog.download_button.isEnabled()
    assert not dialog.install_button.isEnabled()
    assert dialog.installer is None
    assert dialog.progress.value() == 0
    qtbot.waitUntil(lambda: not dialog.timer.isActive())
    assert dialog.status.text() == "Up to date"
    assert dialog.check_button.isEnabled()
    assert not dialog.download_button.isEnabled()
    assert not dialog.install_button.isEnabled()

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
    assert not dialog.check_button.isEnabled()
    done.set()
    qtbot.waitUntil(lambda: dialog.install_button.isEnabled())
    assert dialog.progress.value() == 100
    assert dialog.check_button.isEnabled()
    helper = Mock()
    monkeypatch.setattr(updates, "install_after_exit", helper)
    dialog.cancel_button.click()
    helper.assert_not_called()
    assert dialog.cancelled.is_set()

    for accepted in (False, True):
        events = []
        dialog.controller.window.close = Mock(
            side_effect=lambda events=events, accepted=accepted: (
                events.append("close") or accepted
            )
        )
        dialog.installer = tmp_path / "Setup.exe"
        helper = Mock(side_effect=lambda path, events=events: events.append("helper"))
        monkeypatch.setattr(updates, "install_after_exit", helper)
        application = Mock()
        application.instance.return_value.quit.side_effect = lambda events=events: (
            events.append("quit")
        )
        monkeypatch.setattr(updates, "QApplication", application)
        dialog.install()
        assert events == (["close", "helper", "quit"] if accepted else ["close"])

    dialog.download_button.setEnabled(False)
    dialog.install_button.setEnabled(False)

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
    asset = {
        "name": "Setup.exe",
        "size": 11,
        "browser_download_url": "https://example.test/Setup.exe",
    }
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
    asset = {
        "name": "Setup.exe",
        "size": 100,
        "browser_download_url": "https://example.test/Setup.exe",
    }
    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        updates.download_installer(asset, tmp_path, Event(), Mock())
    assert not (tmp_path / "Setup.exe").exists()
