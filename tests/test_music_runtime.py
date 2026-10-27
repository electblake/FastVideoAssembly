import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
import test_app

from fastvideoassembly import app, music_runtime
from fastvideoassembly.assembly import Clip
from fastvideoassembly.classification import (
    BACKGROUND_LABELS,
    GPU_MODEL_ID,
    WINDOW_SECONDS,
)

controller = test_app.controller
preview_source = test_app.preview_source


@pytest.mark.profile
def test_device_controls_and_restart(controller, qtbot):
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
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.music_device.currentData() == "cuda"
    assert restored.music_precision.currentData() == "float32"
    assert restored.music_gpu_index.value() == 2
    assert restored.music_threads.value() == 8
    assert restored.music_gpu_threads.value() == 2


def test_gpu_requests_and_precision_cache(controller, preview_source, monkeypatch, qtbot):
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
        start(sys.executable, ["-c", (
            "import sys,json; r=json.load(sys.stdin); "
            "[print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))),flush=True) for c in r['clips']]"
        )])

    def send(data):
        requests.append(json.loads(data))
        return write(data)

    monkeypatch.setattr(controller.classification_process, "start", worker)
    monkeypatch.setattr(controller.classification_process, "write", send)
    controller.classify_music()
    qtbot.waitUntil(lambda: not controller.running)
    assert launches[0][1] == ["-m", "fastvideoassembly.music_runtime", "classify"]
    assert requests[0]["device"] == "cuda"
    assert requests[0]["gpu_index"] == 2
    assert requests[0]["threads"] == 1
    assert requests[0]["cache_dir"] == str(music_runtime.model_cache_path())
    controller.classify_music()
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


def test_gpu_apply_uses_current_backend(controller, preview_source):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    key = json.dumps(["music-gpu-v2", GPU_MODEL_ID, "float16", WINDOW_SECONDS,
                      {"music": "music", "talking": "talking"}, BACKGROUND_LABELS, controller.source_audio_key(clip)])
    controller.classification_cache[key] = {"music": 0.9, "talking": 0.1}
    controller.apply_music_threshold()
    assert not controller.audio_muted
    controller.music_device.setCurrentIndex(1)
    controller.apply_music_threshold()
    assert controller.audio_muted == {str(preview_source)}


@pytest.mark.parametrize("operation", ["install", "download"])
def test_setup_buttons_background_busy_state(controller, monkeypatch, qtbot, operation):
    controller.music_device.setCurrentIndex(1)
    start = controller.music_setup_process.start
    calls = []

    def launch(program, args):
        calls.append(args)
        start(sys.executable, ["-c", "print('Setup finished')"])

    monkeypatch.setattr(controller.music_setup_process, "start", launch)
    button = controller.install_music_dependencies if operation == "install" else controller.download_music_model
    button.click()
    assert controller.running
    assert not controller.music_panel.isEnabled()
    assert not controller.assembler.stop_button.isEnabled()
    qtbot.waitUntil(lambda: not controller.running)
    assert calls == [["-m", "fastvideoassembly.music_runtime", operation] +
                     (["cuda"] if operation == "download" else [])]
    assert controller.install_music_dependencies.isEnabled()
    assert "Setup finished" in controller.log.toPlainText()


def test_install_isolated_cuda_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(music_runtime, "gpu_runtime_path", lambda: tmp_path / "gpu")
    run = Mock()
    monkeypatch.setattr(music_runtime.subprocess, "run", run)
    music_runtime.install_gpu_dependencies()
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0][-1] == str(tmp_path / "gpu")
    assert commands[1][commands[1].index("--python") + 1] == str(tmp_path / "gpu/Scripts/python.exe")
    assert commands[1][commands[1].index("--torch-backend") + 1] == "cu130"
    assert all(call.kwargs["check"] for call in run.call_args_list)


def test_install_failure_stops(monkeypatch):
    failure = subprocess.CalledProcessError(1, "uv")
    run = Mock(side_effect=failure)
    monkeypatch.setattr(music_runtime.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError) as raised:
        music_runtime.install_gpu_dependencies()
    assert raised.value is failure
    assert run.call_count == 1


def test_missing_gpu_interpreter_reports_install_action(controller, preview_source, monkeypatch, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.refresh()
    controller.select_clip(clip)
    controller.music_device.setCurrentIndex(1)
    start = controller.classification_process.start
    error = ("error: uv trampoline failed to spawn Python child process\n"
             "  Caused by: entity not found (os error 2)\n")

    def launch(program, args):
        start(sys.executable, ["-c", (
            "import sys,json; json.load(sys.stdin); "
            f"sys.stderr.write({error!r}); sys.exit(1)"
        )])

    monkeypatch.setattr(controller.classification_process, "start", launch)
    controller.classify_music()
    qtbot.waitUntil(lambda: not controller.running)
    message = "GPU runtime could not start. Click Install GPU Dependencies in Music Classification."
    assert error.strip() in controller.log.toPlainText()
    assert message in controller.log.toPlainText()
    assert controller.window.statusBar().currentMessage() == message
    assert controller.progress.format() == "Music Classification failed - %v / %m"
    assert not controller.classification_timer.isActive()
    assert controller.music_panel.isEnabled()
    assert controller.install_music_dependencies.isEnabled()
    assert not controller.classification_cache
    assert not controller.audio_muted

    monkeypatch.setattr(controller.classification_process, "start", lambda program, args: start(
        sys.executable, ["-c", (
            "import sys,json; r=json.load(sys.stdin); "
            "[print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))),flush=True) for c in r['clips']]"
        )]))
    controller.classify_music()
    qtbot.waitUntil(lambda: not controller.running)
    assert controller.classification_error == ""
    assert controller.window.statusBar().currentMessage() == "Music Classification complete"


@pytest.mark.parametrize("device, error", [
    ("cuda", "RuntimeError: CUDA out of memory"),
    ("cpu", "uv trampoline failed to spawn Python child process\nentity not found (os error 2)"),
])
def test_other_classification_failures_propagate(controller, device, error):
    controller.music_device.setCurrentIndex(controller.music_device.findData(device))
    controller.classification_buffer = ""
    controller.classification_error = error
    controller.classification_started = 0
    controller.classification_scanned = 0
    controller.classification_completed = 0
    controller.stop_requested = False
    with pytest.raises(subprocess.CalledProcessError):
        controller.classification_finished(1, controller.classification_process.exitStatus())
    assert "Click Install GPU Dependencies" not in controller.log.toPlainText()


@pytest.mark.parametrize("device, model, weights", [
    ("cpu", "Xenova/clap-htsat-unfused", "onnx/model_fp16.onnx"),
    ("cuda", "laion/clap-htsat-unfused", "pytorch_model.bin"),
])
def test_download_uses_platform_cache(monkeypatch, tmp_path, device, model, weights):
    import huggingface_hub

    monkeypatch.setattr(music_runtime, "user_cache_path", lambda *args, **kwargs: tmp_path)
    download = Mock()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    music_runtime.download_model(device)
    download.assert_called_once_with(model, cache_dir=tmp_path / "huggingface/hub",
                                     allow_patterns=["*.json", "*.txt", weights])
