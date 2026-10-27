# Temporary verification of persisted model authentication and worker token propagation.
# Retire after: first release containing this fix (0.8.5).

import json
import sys

import pytest
from PySide6.QtWidgets import QFormLayout, QLineEdit

from fastvideoassembly import app
from fastvideoassembly.assembly import Clip


@pytest.mark.profile
def test_models_dock_persists_token(controller, qtbot, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test-environment-token")
    assert controller.huggingface_token.text() == ""
    assert controller.models_dock.windowTitle() == "Models"
    assert controller.models_dock.objectName() == "models"
    assert isinstance(controller.models_panel.layout(), QFormLayout)
    assert controller.huggingface_token.echoMode() == QLineEdit.EchoMode.Password
    controller.huggingface_token.setText("test-saved-token")
    controller.settings.sync()
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.huggingface_token.text() == "test-saved-token"
    restored.huggingface_token.clear()
    restored.settings.sync()
    assert restored.settings.value("models/huggingface_token") == ""


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_model_workers_receive_saved_token(controller, preview_source, monkeypatch, qtbot, device):
    monkeypatch.setenv("HF_TOKEN", "test-environment-token")
    controller.huggingface_token.setText("test-saved-token")
    controller.music_device.setCurrentIndex(controller.music_device.findData(device))
    setup_start = controller.music_setup_process.start

    def download(program, arguments):
        assert arguments == ["-m", "fastvideoassembly.music_runtime", "download", device]
        setup_start(sys.executable, ["-c", (
            "import os; from huggingface_hub import get_token; "
            "assert get_token() == 'test-saved-token'; print('Download worker authenticated')"
        )])

    monkeypatch.setattr(controller.music_setup_process, "start", download)
    controller.download_music_model.click()
    assert not controller.models_panel.isEnabled()
    qtbot.waitUntil(lambda: not controller.running)
    assert controller.music_setup_process.exitCode() == 0
    assert controller.models_panel.isEnabled()

    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.refresh()
    controller.select_clip(clip)
    start = controller.classification_process.start

    def classify(program, arguments):
        start(sys.executable, ["-c", (
            "import json,sys; from huggingface_hub import get_token; "
            "assert get_token() == 'test-saved-token'; r=json.load(sys.stdin); "
            "assert 'test-saved-token' not in json.dumps(r); c=r['clips'][0]; "
            "print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))))"
        )])

    monkeypatch.setattr(controller.classification_process, "start", classify)
    controller.classify_music()
    qtbot.waitUntil(lambda: not controller.running)
    assert controller.classification_process.exitCode() == 0
    assert controller.classification_completed == 1
    assert "test-saved-token" not in controller.log.toPlainText()
    assert "test-saved-token" not in json.dumps(controller.classification_cache)

    controller.huggingface_token.clear()
    monkeypatch.setattr(controller.music_setup_process, "start", lambda program, arguments: setup_start(
        sys.executable, ["-c", (
            "from huggingface_hub import get_token; assert get_token() == 'test-environment-token'"
        )]))
    controller.download_music_model.click()
    qtbot.waitUntil(lambda: not controller.running)
    assert controller.music_setup_process.exitCode() == 0
