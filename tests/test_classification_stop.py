# Temporary regression checks for unresponsive classification cancellation.
# Retire after: first release containing this fix (0.8.5).

import sys

import pytest
from PySide6.QtCore import QTimer

from fastvideoassembly.assembly import Clip


def test_timeline_classification_stop_interrupts_worker(controller, preview_source, monkeypatch, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.assembler.tracks = [[clip], [], []]
    controller.refresh()
    stop = controller.assembler.classification_stop_button
    assert not stop.isEnabled()
    start = controller.classification_process.start

    def worker(program, arguments):
        start(sys.executable, ["-c", (
            "import sys,json,time; r=json.load(sys.stdin); c=r['clips'][0]; "
            "print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))),flush=True); "
            "time.sleep(60)"
        )])

    monkeypatch.setattr(controller.classification_process, "start", worker)
    controller.assembler.classify_timelines_button.click()
    qtbot.waitUntil(lambda: controller.classification_completed == 1)
    assert stop.isEnabled()
    stop.click()
    qtbot.waitUntil(lambda: not controller.running)
    assert not stop.isEnabled()
    assert not controller.classification_timer.isActive()
    assert controller.window.statusBar().currentMessage() == "Audio Classification stopped"
    assert list(controller.classification_cache.values()) == [{"music": 0.8, "talking": 0.1}]


def test_stop_during_classification_preparation(controller, preview_source, monkeypatch, qtbot):
    clips = [Clip(preview_source, duration, 60, 120, True) for duration in range(1, 101)]
    controller.clips = clips
    controller.assembler.tracks = [clips, [], []]
    controller.refresh()
    processed = []
    key = controller.source_audio_key

    def source_key(clip):
        processed.append(clip)
        QTimer.singleShot(0, controller.assembler.classification_stop_button.click)
        return key(clip)

    monkeypatch.setattr(controller, "source_audio_key", source_key)
    controller.assembler.classify_timelines_button.click()
    assert controller.assembler.classification_stop_button.isEnabled()
    qtbot.waitUntil(lambda: not controller.running)
    assert 0 < len(processed) < len(clips)
    assert not controller.classification_prepare_timer.isActive()
    assert controller.classification_process.processId() == 0
    assert controller.window.statusBar().currentMessage() == "Audio Classification stopped"


@pytest.mark.parametrize("during_start", [False, True])
def test_stop_before_first_classification_result(controller, preview_source, monkeypatch, qtbot, during_start):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.assembler.tracks = [[clip], [], []]
    controller.refresh()
    start = controller.classification_process.start

    def worker(program, arguments):
        start(sys.executable, ["-c", "import time; time.sleep(60)"])
        if during_start:
            controller.assembler.classification_stop_button.click()

    monkeypatch.setattr(controller.classification_process, "start", worker)
    controller.assembler.classify_timelines_button.click()
    if not during_start:
        qtbot.waitUntil(lambda: controller.classification_process.processId() != 0)
        assert controller.assembler.classification_stop_button.isEnabled()
        controller.assembler.classification_stop_button.click()
    qtbot.waitUntil(lambda: not controller.running)
    assert controller.classification_completed == 0
    assert controller.window.statusBar().currentMessage() == "Audio Classification stopped"
    assert not controller.assembler.classification_stop_button.isEnabled()
