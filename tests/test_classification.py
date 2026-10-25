import io
import json
import math
import subprocess
import sys
from dataclasses import replace
from threading import Barrier, get_ident
from unittest.mock import Mock

import pytest
import test_app
from test_audio import measure

from fastvideoassembly import app, classification
from fastvideoassembly.assembly import (
    Clip,
    RenderConfig,
    column_arguments,
    division_arguments,
)
from fastvideoassembly.classification import (
    BACKGROUND_LABELS,
    MODEL_FILE,
    MODEL_ID,
    WINDOW_SECONDS,
    classify_clip,
)

controller = test_app.controller
preview_source = test_app.preview_source


@pytest.mark.profile
def test_cached_classification_mute_and_restart(controller, preview_source, qtbot, monkeypatch):
    assert controller.talking_label.text() == "talking"
    assert controller.talking_threshold.value() == 0.5
    assert not controller.mute_talking.isChecked()
    assert controller.music_threads.value() == 1
    controller.music_threads.setValue(2)
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.assembler.tracks = [[clip], [clip], []]
    controller.refresh()
    controller.select_clip(clip)
    key = json.dumps(["music-v2", MODEL_ID, MODEL_FILE, WINDOW_SECONDS, {"music": "music", "talking": "talking"},
                      BACKGROUND_LABELS, controller.source_audio_key(clip)])
    controller.classification_cache[key] = {"music": 0.8, "talking": 0.1}
    start = Mock()
    monkeypatch.setattr(controller.classification_process, "start", start)
    controller.music_threshold.setValue(0.9)
    controller.classify_music()
    assert not controller.audio_muted
    controller.music_threshold.setValue(0.7)
    controller.classify_music(timelines=True)
    start.assert_not_called()
    assert controller.classification_completed == 1
    assert controller.progress.format().endswith("0.0 it/s - ETA 00:00:00")
    assert not controller.classification_timer.isActive()
    assert controller.audio_muted == {str(preview_source)}
    assert controller.preview.mute_checkbox.isChecked()
    assert controller.preview.audio.isMuted()
    controller.normalization.setCurrentText("True Peak")
    assert not controller.normalize_button.isEnabled()
    controller.talking_threshold.setValue(0.6)
    controller.mute_talking.setChecked(True)
    restored = app.Application()
    qtbot.addWidget(restored.window)
    assert restored.music_threads.value() == 2
    assert restored.talking_threshold.value() == 0.6
    assert restored.mute_talking.isChecked()
    assert restored.classification_cache == controller.classification_cache
    assert restored.audio_muted == controller.audio_muted
    restored.select_clip(clip)
    assert restored.preview.mute_checkbox.isChecked()
    restored.preview.mute_checkbox.click()
    assert not restored.audio_muted
    assert not restored.preview.audio.isMuted()


@pytest.mark.profile
def test_apply_threshold_resets_all_cached_clips(controller, preview_source, tmp_path, monkeypatch):
    clips = [Clip(preview_source, 3, 60, 120, True)]
    for name in ("other", "unclassified", "changed"):
        path = tmp_path / f"{name}.mp4"
        path.write_bytes(preview_source.read_bytes())
        clips.append(Clip(path, 3, 60, 120, True))
    controller.clips = clips
    controller.refresh()
    controller.select_clip(clips[0])
    for clip, score in zip([clips[0], clips[1], clips[3]], [0.8, 0.4, 0.9]):
        key = json.dumps(["music-v2", MODEL_ID, MODEL_FILE, WINDOW_SECONDS, {"music": "music", "talking": "talking"},
                          BACKGROUND_LABELS, controller.source_audio_key(clip)])
        controller.classification_cache[key] = {"music": score, "talking": 0.1}
    clips[3].path.write_bytes(clips[3].path.read_bytes() + b"changed")
    cached = dict(controller.classification_cache)
    controller.audio_muted = {str(clip.path) for clip in clips}
    start = Mock()
    monkeypatch.setattr(controller.classification_process, "start", start)
    controller.music_threshold.setValue(0.9)
    controller.apply_music_threshold_button.click()
    assert controller.audio_muted == {str(clips[2].path), str(clips[3].path)}
    assert not controller.preview.mute_checkbox.isChecked()
    assert not controller.preview.audio.isMuted()
    controller.music_threshold.setValue(0.4)
    controller.apply_music_threshold_button.click()
    assert controller.audio_muted == {str(clip.path) for clip in clips}
    assert controller.preview.mute_checkbox.isChecked()
    assert controller.preview.audio.isMuted()
    assert set(json.loads(controller.settings.value("audio/muted"))) == controller.audio_muted
    controller.mute_music.setChecked(False)
    controller.apply_music_threshold_button.click()
    assert controller.audio_muted == {str(clips[2].path), str(clips[3].path)}
    controller.music_label.setText("instrumental music")
    controller.mute_music.setChecked(True)
    controller.apply_music_threshold_button.click()
    assert controller.audio_muted == {str(clips[2].path), str(clips[3].path)}
    assert controller.classification_cache == cached
    start.assert_not_called()


def test_normalization_skips_muted_sources(controller, preview_source, monkeypatch):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.audio_muted.add(str(preview_source))
    controller.normalization.setCurrentText("True Peak")
    start = Mock()
    monkeypatch.setattr(controller, "start_export_job", start)
    controller.normalize_audio()
    start.assert_not_called()
    assert controller.measurement_keys == {}
    assert controller.export_jobs == []


@pytest.mark.parametrize("mode", ["None", "True Peak", "YouTube"])
@pytest.mark.parametrize("direct", [False, True])
def test_muted_render_is_silent(preview_source, tmp_path, mode, direct):
    clip = Clip(preview_source, 3, 60, 120, True)
    config = RenderConfig(column_width=60, height=120, encoder="libx264", normalization=mode,
                          audio_gains={str(preview_source): 60}, audio_muted={str(preview_source)})
    output = tmp_path / "muted.mp4"
    graph = tmp_path / "muted.ffgraph"
    if direct:
        args = division_arguments([[clip], [clip]], 3, output, graph, config, {}, peak=-math.inf)
    else:
        args = column_arguments([clip], output, graph, config, {})
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    assert float(measure(output)["input_tp"]) == -math.inf
    assert "[0:a:0]" not in graph.read_text()


@pytest.mark.parametrize("interims", [False, True])
def test_muted_export_omits_measurements(controller, preview_source, tmp_path, monkeypatch, interims):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.assembler.tracks = [[clip]] * 3
    controller.audio_muted.add(str(preview_source))
    controller.assembler.render_timelines.setChecked(interims)
    config = replace(controller.render_config(), normalization="True Peak")
    monkeypatch.setattr(controller, "render_config", lambda: config)
    monkeypatch.setattr(controller, "start_export_job", Mock())
    controller.start_export(tmp_path / "export.mp4")
    assert controller.measurement_keys == {}
    assert controller.audio_peaks[tmp_path / "export_FINAL.mp4"] == -math.inf
    controller.running = False
    controller.export_directory.cleanup()
    controller.export_directory = None


def test_classifies_entire_clip(preview_source):
    calls = []

    def classifier(audio, candidate_labels):
        calls.append((len(audio), candidate_labels))
        return [{"label": "music", "score": len(calls) / 10}, {"label": "talking", "score": 0.7}]

    score = classify_clip(classifier, "ffmpeg", str(preview_source), 3, {"music": "music", "talking": "talking"})
    assert score == {"music": 0.1, "talking": 0.7}
    assert calls == [(144000, ["music", "talking", *BACKGROUND_LABELS])]


def test_worker_selection_and_cache_invalidation(controller, preview_source, tmp_path, qtbot, monkeypatch):
    other_path = tmp_path / "other.mp4"
    other_path.write_bytes(preview_source.read_bytes())
    clip = Clip(preview_source, 3, 60, 120, True)
    other = Clip(other_path, 3, 60, 120, True)
    controller.clips = [clip, other]
    controller.assembler.tracks = [[clip], [other], [other]]
    controller.refresh()
    controller.assembler.selected_timelines = {1, 2}
    controller.mute_music.setChecked(False)
    start = controller.classification_process.start
    launches = []
    write = controller.classification_process.write
    requests = []

    def send_request(data):
        requests.append(json.loads(data))
        return write(data)

    def worker(program, arguments):
        launches.append(arguments)
        start(sys.executable, ["-c", ("import sys,json; request=json.load(sys.stdin); "
              "[print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))),flush=True) "
              "for c in request['clips']]")])

    monkeypatch.setattr(controller.classification_process, "start", worker)
    monkeypatch.setattr(controller.classification_process, "write", send_request)
    controller.classify_music(timelines=True)
    assert not controller.music_panel.isEnabled()
    assert controller.classification_timer.isActive()
    assert not controller.assembler.classify_clips_button.isEnabled()
    qtbot.waitUntil(lambda: not controller.running)
    assert not controller.classification_timer.isActive()
    assert controller.progress.format().endswith("ETA 00:00:00")
    assert controller.classification_completed == 1
    assert not controller.audio_muted
    assert all(json.loads(key)[-1][0] == str(other_path.resolve())
               for key in controller.classification_cache)
    controller.music_threshold.setValue(0.7)
    controller.music_threads.setValue(3)
    controller.mute_music.setChecked(True)
    controller.classify_music(timelines=True)
    assert len(launches) == 1
    assert controller.audio_muted == {str(other_path)}
    controller.music_label.setText("instrumental music")
    controller.classify_music(timelines=True)
    qtbot.waitUntil(lambda: not controller.running)
    assert len(launches) == 2
    other_path.write_bytes(other_path.read_bytes() + b"changed")
    controller.classify_music(timelines=True)
    qtbot.waitUntil(lambda: not controller.running)
    assert len(launches) == 3
    assert [request["threads"] for request in requests] == [1, 3, 3]
    assert len(controller.classification_cache) == 3
    controller.talking_label.setText("conversation")
    controller.classify_music(timelines=True)
    qtbot.waitUntil(lambda: not controller.running)
    assert len(launches) == 4
    assert requests[-1]["labels"] == {"music": "instrumental music", "talking": "conversation"}


def test_classification_checks_late_audio(tmp_path):
    source = tmp_path / "long.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=12", str(source)], check=True)
    sizes = []

    def classifier(audio, candidate_labels):
        sizes.append(len(audio))
        return [{"label": "music", "score": 0.2 if len(sizes) == 1 else 0.9},
                {"label": "talking", "score": 0.8 if len(sizes) == 1 else 0.1}]

    assert classify_clip(classifier, "ffmpeg", str(source), 12, {"music": "music", "talking": "talking"}) == {"music": 0.9, "talking": 0.8}
    assert sizes == [480000, 96000]


def test_audio_shorter_than_video_only_classifies_actual_samples(tmp_path):
    source = tmp_path / "short-audio.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=size=16x16:rate=1:duration=21", "-f", "lavfi", "-i",
                    "sine=sample_rate=48000:duration=2", "-c:v", "libx264", str(source)], check=True)
    sizes = []

    def classifier(audio, candidate_labels):
        sizes.append(len(audio))
        return [{"label": "music", "score": 0.2}, {"label": "talking", "score": 0.8}]

    assert classify_clip(classifier, "ffmpeg", str(source), 21,
                         {"music": "music", "talking": "talking"}) == {"music": 0.2, "talking": 0.8}
    assert len(sizes) == 1
    assert 96000 <= sizes[0] < 100000


def test_failed_worker_does_not_process_remaining_queue(monkeypatch):
    create = Mock(side_effect=RuntimeError("inference failed"))
    monkeypatch.setattr(classification, "create_classifier", create)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "threads": 1, "ffmpeg": "ffmpeg", "labels": {"music": "music", "talking": "talking"},
        "device": "cpu", "precision": "float16", "gpu_index": 0, "cache_dir": "models",
        "clips": [{"key": str(index), "path": "clip.mp4", "duration": 1} for index in range(100)],
    })))
    with pytest.raises(RuntimeError, match="inference failed"):
        classification.main()
    assert create.call_count == 1


def test_classification_rate_and_eta_exclude_cached_items(controller, monkeypatch):
    clock = [110.0]
    monkeypatch.setattr(app, "monotonic", lambda: clock[0])
    controller.classification_started = 100.0
    controller.classification_scanned = 20
    controller.classification_completed = 120
    controller.progress.setRange(0, 200)
    controller.update_classification_progress()
    assert controller.progress.format() == "Music Classification - %v / %m - 2.0 it/s - ETA 00:00:40"
    clock[0] = 120.0
    controller.update_classification_progress()
    assert controller.progress.format().endswith("1.0 it/s - ETA 00:01:20")
    controller.classification_scanned = 100
    controller.classification_completed = 200
    controller.update_classification_progress()
    assert controller.progress.format().endswith("5.0 it/s - ETA 00:00:00")
    controller.classification_scanned = 0
    controller.classification_completed = 100
    controller.update_classification_progress()
    assert controller.progress.format().endswith("0.0 it/s - ETA --:--:--")


@pytest.mark.parametrize("threads", [1, 2])
def test_worker_threads_own_and_reuse_classifiers(monkeypatch, capsys, threads):
    barrier = Barrier(threads)
    classifiers = []
    request = {"threads": threads, "ffmpeg": "ffmpeg", "labels": {"music": "music", "talking": "talking"},
               "device": "cpu", "precision": "float16", "gpu_index": 0, "cache_dir": "models",
               "clips": [{"key": str(index), "path": str(index), "duration": 1}
                         for index in range(4)]}

    def create(device, precision, gpu_index, cache_dir):
        assert (device, precision, gpu_index, cache_dir) == ("cpu", "float16", 0, "models")
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
        {"key": str(index), "path": str(index), "score": {"music": index / 10, "talking": 0.1}} for index in range(4)]


def test_worker_failure_propagates(monkeypatch):
    error = RuntimeError("inference failed")
    monkeypatch.setattr(classification, "create_classifier", Mock(side_effect=error))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "threads": 2, "ffmpeg": "ffmpeg", "labels": {"music": "music", "talking": "talking"},
        "device": "cpu", "precision": "float16", "gpu_index": 0, "cache_dir": "models",
        "clips": [{"key": "clip", "path": "clip.mp4", "duration": 1}],
    })))
    with pytest.raises(RuntimeError) as raised:
        classification.main()
    assert raised.value is error


def test_talking_mute_and_apply_preserves_music_matches(controller, preview_source, tmp_path, monkeypatch):
    other = tmp_path / "talking.mp4"
    other.write_bytes(preview_source.read_bytes())
    clips = [Clip(path, 3, 60, 120, True) for path in (preview_source, other)]
    controller.clips = clips
    controller.refresh()
    controller.select_clip(clips[1])
    for clip, scores in zip(clips, [{"music": 0.8, "talking": 0.1}, {"music": 0.1, "talking": 0.8}]):
        key = json.dumps(["music-v2", MODEL_ID, MODEL_FILE, WINDOW_SECONDS,
                          {"music": "music", "talking": "talking"}, BACKGROUND_LABELS,
                          controller.source_audio_key(clip)])
        controller.classification_cache[key] = scores
    start = Mock()
    monkeypatch.setattr(controller.classification_process, "start", start)
    controller.mute_talking.setChecked(True)
    controller.classify_music()
    assert controller.audio_muted == {str(other)}
    assert controller.preview.audio.isMuted()
    controller.apply_talking_threshold_button.click()
    assert controller.audio_muted == {str(preview_source), str(other)}
    controller.talking_threshold.setValue(0.9)
    controller.apply_talking_threshold_button.click()
    assert controller.audio_muted == {str(preview_source)}
    assert not controller.preview.mute_checkbox.isChecked()
    controller.mute_music.setChecked(False)
    controller.talking_threshold.setValue(0.5)
    controller.apply_music_threshold_button.click()
    assert controller.audio_muted == {str(other)}
    start.assert_not_called()


def test_stop_classification_terminates_process_tree(controller, preview_source, monkeypatch, qtbot):
    clip = Clip(preview_source, 3, 60, 120, True)
    controller.clips = [clip]
    controller.refresh()
    controller.select_clip(clip)
    start = controller.classification_process.start

    def worker(program, arguments):
        start(sys.executable, ["-c", (
            "import sys,time,json; r=json.load(sys.stdin); c=r['clips'][0]; "
            "print(json.dumps(dict(key=c['key'],path=c['path'],score=dict(music=0.8,talking=0.1))),flush=True); "
            "time.sleep(60)"
        )])

    monkeypatch.setattr(controller.classification_process, "start", worker)
    controller.classify_music()
    qtbot.waitUntil(lambda: controller.classification_completed == 1)
    assert controller.assembler.stop_button.isEnabled()
    controller.assembler.stop_button.click()
    qtbot.waitUntil(lambda: not controller.running)
    assert not controller.classification_timer.isActive()
    assert controller.window.statusBar().currentMessage() == "Music Classification stopped"
    assert controller.progress.format() == "Music Classification stopped - %v / %m"
    assert controller.music_panel.isEnabled()
    assert not controller.assembler.stop_button.isEnabled()
    assert list(controller.classification_cache.values()) == [{"music": 0.8, "talking": 0.1}]
    assert controller.audio_muted == {str(preview_source)}
