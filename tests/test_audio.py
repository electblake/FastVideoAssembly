import json
import math
import subprocess

import pytest

from fastvideoassembly.assembly import (
    Clip,
    RenderConfig,
    column_jobs,
    composition_arguments,
)
from fastvideoassembly.audio import (
    mix_peak_arguments,
    normalization_filter,
    peak_measurement_arguments,
)


def measure(path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            "loudnorm=I=-14:TP=-1:LRA=50:print_format=json",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(
        result.stderr[result.stderr.rindex("{") : result.stderr.rindex("}") + 1]
    )


@pytest.mark.parametrize("mode", ["None", "True Peak", "YouTube"])
def test_normalization_levels_and_silence(mode, tmp_path):
    levels = []
    for gain in ("0.1", "1", "0"):
        source = tmp_path / f"source{gain}.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=997:sample_rate=48000:duration=4,volume={gain}",
                "-ac",
                "2",
                "-c:a",
                "pcm_f32le",
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        original = measure(source)
        clip = Clip(source, 4, 1, 1, True)
        measured = subprocess.run(
            ["ffmpeg", *peak_measurement_arguments(clip)],
            check=True,
            capture_output=True,
            text=True,
        )
        peak = float(
            json.loads(
                measured.stderr[
                    measured.stderr.rindex("{") : measured.stderr.rindex("}") + 1
                ]
            )["input_tp"]
        )
        output = tmp_path / f"normalized{gain}.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(source),
                "-af",
                normalization_filter(mode, peak),
                "-c:a",
                "pcm_f32le",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        result = measure(output)
        if gain == "0":
            assert float(result["input_tp"]) == -math.inf
        elif mode == "True Peak":
            assert float(result["input_tp"]) == pytest.approx(-1, abs=0.1)
        elif mode == "YouTube":
            assert float(result["input_i"]) == pytest.approx(-14, abs=0.3)
            assert float(result["input_tp"]) <= -0.9
        else:
            assert float(result["input_i"]) == pytest.approx(
                float(original["input_i"]), abs=0.05
            )
        levels.append(float(result["input_i"]))
    assert (
        abs(levels[0] - levels[1]) < 0.3
        if mode != "None"
        else abs(levels[0] - levels[1]) > 19
    )


@pytest.mark.parametrize("mode", ["True Peak", "YouTube"])
def test_column_and_final_normalization(mode, tmp_path, qtbot, monkeypatch):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=60x120:r=30:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=4",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    clip = Clip(source, 4, 60, 120, True)
    measurement = subprocess.run(
        ["ffmpeg", *peak_measurement_arguments(clip)],
        check=True,
        capture_output=True,
        text=True,
    )
    peak = float(
        json.loads(
            measurement.stderr[
                measurement.stderr.rindex("{") : measurement.stderr.rindex("}") + 1
            ]
        )["input_tp"]
    )
    config = RenderConfig(
        column_width=64, height=120, encoder="libx264", normalization=mode
    )
    column = tmp_path / "column.mp4"
    jobs = column_jobs(
        [Clip(source, 4, 60, 120, True)],
        column,
        tmp_path / "column.txt",
        config,
        {source: peak},
    )
    for _, _, args in jobs:
        args = args() if callable(args) else args
        subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    columns = [column] * 3
    measurement = subprocess.run(
        ["ffmpeg", *mix_peak_arguments(columns, 4)],
        check=True,
        capture_output=True,
        text=True,
    )
    final_peak = float(
        json.loads(
            measurement.stderr[
                measurement.stderr.rindex("{") : measurement.stderr.rindex("}") + 1
            ]
        )["input_tp"]
    )
    final = tmp_path / "final.mp4"
    args = composition_arguments(
        columns, 4, final, tmp_path / "final.txt", config, final_peak
    )
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    for path in (column, final):
        result = measure(path)
        if mode == "True Peak":
            assert float(result["input_tp"]) == pytest.approx(-1, abs=0.5)
        else:
            assert float(result["input_i"]) == pytest.approx(-14, abs=0.5)

    from fastvideoassembly import app

    monkeypatch.setattr(
        app, "user_config_path", lambda *args, **kwargs: tmp_path / "settings"
    )
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.normalization.setCurrentText(mode)
    monkeypatch.setattr(controller, "render_config", lambda: config)
    controller.tracks = [[clip], [clip], [clip]]
    gui_output = tmp_path / "queued.mp4"
    controller.start_export(gui_output)
    gui_output = controller.output
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.process.exitCode() == 0, controller.log.toPlainText()
    result = measure(gui_output)
    if mode == "True Peak":
        assert len(controller.measurement_keys) == 2
        assert set(controller.audio_peaks) == {source, gui_output}
        assert float(result["input_tp"]) == pytest.approx(-1, abs=0.5)
    else:
        assert float(result["input_i"]) == pytest.approx(-14, abs=0.5)
