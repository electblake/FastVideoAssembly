import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from fastvideoassembly.assembly import (
    Clip,
    RenderConfig,
    balance,
    clip_duration,
    clip_from_probe,
    column_jobs,
    composition_arguments,
    track_durations,
    video_paths,
)


def test_balanced_tracks_keep_every_portrait_once_and_ascending():
    clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 10)]
    tracks = balance(clips)
    assert sorted(clip.duration for track in tracks for clip in track) == list(
        range(1, 10)
    )
    assert track_durations(tracks) == [16, 15, 14]
    assert all(
        track == sorted(track, key=lambda clip: clip.duration) for track in tracks
    )


def test_duration_allocator_does_not_filter_source_shapes():
    clips = [
        Clip(Path(f"clip{i}.mp4"), i + 1, width, height)
        for i, (width, height) in enumerate([(60, 120), (120, 60), (120, 120)])
    ]
    assert {clip for track in balance(clips) for clip in track} == set(clips)


def test_longest_first_preserves_track_membership_and_totals():
    clips = [
        Clip(Path(f"{n}.mp4"), n, 90, 160) for n in [1, 1, 3, 5, 8, 40, 600, 1200, 1975]
    ]
    ascending = balance(clips)
    descending = balance(clips, longest_first=True)
    assert track_durations(descending) == track_durations(ascending)
    for original, ordered in zip(ascending, descending):
        assert sorted(c.path for c in ordered) == sorted(c.path for c in original)
        durations = [clip.duration for clip in ordered]
        assert durations == sorted(durations, reverse=True)
    assert balance(clips, longest_first=True) == descending
    assert balance([], longest_first=True) == [[], [], []]


def test_metadata_uses_rotation_and_pixel_aspect_ratio():
    metadata = {
        "streams": [
            {
                "width": 160,
                "codec_type": "video",
                "height": 90,
                "sample_aspect_ratio": "1:1",
                "side_data_list": [{"rotation": -90}],
            }
        ],
        "format": {"duration": "2.5"},
    }
    clip = clip_from_probe(Path("rotated.mp4"), metadata)
    assert clip.portrait
    assert (clip.width, clip.height, clip.duration) == (90, 160, 2.5)
    metadata["streams"][0] = {
        "codec_type": "video",
        "width": 90,
        "height": 160,
        "sample_aspect_ratio": "2:1",
    }
    assert not clip_from_probe(Path("anamorphic.mp4"), metadata).portrait


def test_folder_inputs_are_nonrecursive_and_deduplicated(tmp_path):
    video = tmp_path / "one.MP4"
    video.touch()
    (tmp_path / "notes.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "two.mp4").touch()
    assert video_paths([tmp_path, video]) == [video]


def test_center_crop_removes_edges_without_padding(tmp_path):
    source = tmp_path / "striped.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=120x120:r=24:d=0.5,drawbox=x=28:y=0:w=64:h=120:color=lime:t=fill",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    output = tmp_path / "cropped.mp4"
    config = RenderConfig(column_width=64, height=120, fps="24", encoder="libx264")
    jobs = column_jobs(
        [Clip(source, 0.5, 120, 120)], output, tmp_path / "crop.txt", config
    )
    for _, _, args in jobs:
        args = args() if callable(args) else args
        subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    frame = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert len(frame) == 64 * 120 * 3
    for x in (4, 32, 59):
        offset = (60 * 64 + x) * 3
        assert tuple(frame[offset : offset + 3]) == pytest.approx((0, 255, 0), abs=15)


@pytest.mark.parametrize("audio_codec", ["aac", "libmp3lame", "ac3", "eac3"])
def test_audio_survives_columns_silence_gaps_and_three_way_mix(tmp_path, audio_codec):
    clips = []
    for frequency, duration in [(440, 0.6), (660, 1.5), (880, 1.5), (0, 0.3)]:
        path = tmp_path / f"tone{frequency}.mp4"
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=blue:s=60x120:r=30:d={duration}",
        ]
        if frequency:
            command += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=44100:duration={duration}",
                "-c:a",
                "aac",
            ]
        subprocess.run(
            [*command, "-c:v", "libx264", str(path)], check=True, capture_output=True
        )
        metadata = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        clips.append(clip_from_probe(path, json.loads(metadata.stdout)))
    assert [clip.has_audio for clip in clips] == [True, True, True, False]
    tracks = [[clips[0], clips[3], clips[0]], [clips[1]], [clips[2]]]
    config = RenderConfig(
        column_width=64, height=120, encoder="libx264", audio_codec=audio_codec
    )
    columns = []
    for index, track in enumerate(tracks):
        output = tmp_path / f"column{index}.mp4"
        columns.append(output)
        jobs = column_jobs(track, output, tmp_path / f"column{index}.txt", config)
        for _, _, args in jobs:
            args = args() if callable(args) else args
            subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    final = tmp_path / "final.mp4"
    args = composition_arguments(columns, 1.5, final, tmp_path / "mix.txt", config)
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    for path in [*columns, final]:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        expected_codec = "mp3" if audio_codec == "libmp3lame" else audio_codec
        assert json.loads(result.stdout)["streams"][0]["codec_name"] == expected_codec
    for path, times in [
        (columns[0], [(0.2, True), (0.7, False), (1.1, True)]),
        (final, [(0.2, True)]),
    ]:
        for start, audible in times:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    str(start),
                    "-i",
                    str(path),
                    "-t",
                    "0.1",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "48000",
                    "-f",
                    "f32le",
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
            )
            samples = np.frombuffer(result.stdout, dtype="<f4")
            rms = np.sqrt(np.mean(samples**2))
            assert rms > 0.01 if audible else rms < 0.001
            if path == final:
                spectrum = np.abs(np.fft.rfft(samples))
                frequencies = np.fft.rfftfreq(len(samples), 1 / 48000)
                for tone in (440, 660, 880):
                    amplitude = spectrum[np.abs(frequencies - tone).argmin()]
                    assert amplitude > spectrum.max() * 0.4


@pytest.fixture
def media(tmp_path):
    clips = []
    for name, color, duration in [
        ("red", "red", 0.4),
        ("green", "lime", 0.8),
        ("blue", "blue", 1.2),
        ("yellow", "yellow", 0.4),
    ]:
        path = tmp_path / f"{name}.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=60x120:r=30:d={duration}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
        )
        clips.append(Clip(path, duration, 60, 120))
    return clips


def test_render_column_positions_order_center_fill_and_final_frame_hold(
    media, tmp_path
):
    red, green, blue, yellow = media
    tracks = [[red, yellow], [green], [blue]]
    output = tmp_path / "assembled.mp4"
    config = RenderConfig(column_width=64, height=120, encoder="libx264")
    columns = []
    for index, track in enumerate(tracks):
        path = tmp_path / f"column{index}.mp4"
        columns.append(path)
        jobs = column_jobs(track, path, tmp_path / f"column{index}.txt", config)
        for _, _, args in jobs:
            args = args() if callable(args) else args
            subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    args = composition_arguments(columns, 1.2, output, tmp_path / "graph.txt", config)
    subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    metadata = json.loads(result.stdout)
    assert len(metadata["streams"]) == 2
    assert metadata["streams"][1]["codec_name"] == "aac"
    assert (metadata["streams"][0]["width"], metadata["streams"][0]["height"]) == (
        192,
        120,
    )
    assert metadata["streams"][0]["avg_frame_rate"] == "30/1"
    assert float(metadata["format"]["duration"]) == pytest.approx(1.2, abs=0.05)
    for time, expected_left in [
        (0.1, (255, 0, 0)),
        (0.6, (255, 255, 0)),
        (1.1, (255, 255, 0)),
    ]:
        frame = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(time),
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout
        for x, expected in [
            (1, expected_left),
            (32, expected_left),
            (96, (0, 255, 0)),
            (160, (0, 0, 255)),
        ]:
            pixel = frame[(60 * 192 + x) * 3 : (60 * 192 + x) * 3 + 3]
            assert tuple(pixel) == pytest.approx(expected, abs=15)
    # FFmpeg's -n protects source files and existing outputs directly.
    existing = output.read_bytes()
    second = subprocess.run(["ffmpeg", *args], check=False, capture_output=True)
    assert b"already exists" in second.stderr
    assert output.read_bytes() == existing


@pytest.mark.parametrize("combine", [True, False])
def test_gui_import_and_full_resolution_export(
    media, tmp_path, qtbot, monkeypatch, combine
):
    from fastvideoassembly import app

    monkeypatch.setattr(
        app, "user_config_path", lambda *args, **kwargs: tmp_path / "settings"
    )
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.window.show()
    controller.combine.setChecked(combine)
    controller.add_paths([clip.path for clip in media])
    qtbot.waitUntil(lambda: not controller.loading, timeout=30000)
    assert len(controller.clips) == 4
    assert not controller.assembler.export_button.isEnabled()
    controller.assembler.create_button.click()
    assert controller.assembler.export_button.isEnabled()
    output = tmp_path / "gui-output.mp4"
    controller.start_export(output)
    output = controller.output
    assert not controller.assembler.balance_button.isEnabled()
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.process.exitCode() == 0
    assert output.exists() == combine
    inspected = output if combine else output.with_name("gui-output_A.mp4")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(inspected),
        ],
        check=True,
        capture_output=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    assert (stream["width"], stream["height"]) == (1920 if combine else 640, 1080)
    assert controller.progress.value() > 900

    assert stream["codec_name"] == "hevc"
    assert stream["pix_fmt"] == "yuv420p10le"
    for name in ("A", "B", "C"):
        assert output.with_name(f"gui-output_{name}.mp4").stat().st_size > 0
    assert controller.export_directory is None


def test_hundreds_of_clips_have_one_input_and_no_accumulated_av_drift(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=60x120:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    track = []
    for index in range(201):
        path = tmp_path / f"source-{index}.mp4"
        path.hardlink_to(source)
        track.append(Clip(path, 0.101 if index % 2 else 0.167, 60, 120, True))
    config = RenderConfig(
        column_width=64, height=120, fps="30000/1001", encoder="libx264"
    )
    output = tmp_path / "long_A.mp4"
    for _, _, args in column_jobs(track, output, tmp_path / "long.ffconcat", config):
        args = args() if callable(args) else args
        assert args.count("-i") == 1
        result = subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
        assert b"Non-monotonic" not in result.stderr
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
        check=True,
        capture_output=True,
    )
    video, audio = json.loads(result.stdout)["streams"]
    expected = sum(clip_duration(clip, config) for clip in track)
    assert int(video["nb_frames"]) == 101 * 6 + 100 * 4
    assert float(video["duration"]) == pytest.approx(expected, abs=0.002)
    assert float(audio["duration"]) == pytest.approx(expected, abs=0.025)
    assert abs(float(video["start_time"]) - float(audio["start_time"])) < 0.002


def test_stop_removes_intermediates_and_does_not_start_next_clip(
    media, tmp_path, qtbot, monkeypatch
):
    from fastvideoassembly import app

    monkeypatch.setattr(
        app, "user_config_path", lambda *args, **kwargs: tmp_path / "settings"
    )
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.assembler.tracks = [[media[0]] * 200 for _ in range(3)]
    monkeypatch.setattr(
        controller,
        "render_config",
        lambda: RenderConfig(column_width=64, height=120, encoder="libx264"),
    )
    output = tmp_path / "stopped.mp4"
    with qtbot.waitSignal(controller.process.started, timeout=10000):
        controller.start_export(output)
    temporary = Path(controller.export_directory.name)
    controller.stop_export()
    qtbot.waitUntil(lambda: not controller.running, timeout=30000)
    assert controller.export_index == 0
    assert controller.export_directory is None
    assert not temporary.exists()
    assert not output.with_name("stopped_A.mp4").exists()


@pytest.mark.parametrize("mode", ["None", "True Peak", "YouTube"])
def test_source_audio_offset_survives_silent_clip_and_normalization(tmp_path, mode):
    from fastvideoassembly.audio import peak_measurement_arguments

    source = tmp_path / "delayed.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=60x120:r=30:d=2",
            "-itsoffset",
            "0.6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-output_ts_offset",
            "5",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    clip = Clip(source, 2, 60, 120, True)
    measurement = subprocess.run(
        ["ffmpeg", *peak_measurement_arguments(clip)],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    peak = float(
        json.loads(measurement[measurement.rindex("{") : measurement.rindex("}") + 1])[
            "input_tp"
        ]
    )
    config = RenderConfig(
        column_width=64, height=120, encoder="libx264", normalization=mode
    )
    output = tmp_path / "offset_A.mp4"
    # The preceding video has no audio, followed by a clip with delayed audio.
    for _, _, args in column_jobs(
        [Clip(source, 1.1, 60, 120, False), clip],
        output,
        tmp_path / "offset.ffconcat",
        config,
        {source: peak},
    ):
        args = args() if callable(args) else args
        subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
    samples = np.frombuffer(
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(output),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "48000",
                "-f",
                "f32le",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout,
        dtype="<f4",
    )
    for start, audible in [(0.3, False), (1.3, False), (1.9, True), (2.9, False)]:
        window = samples[round(start * 48000) : round((start + 0.1) * 48000)]
        rms = np.sqrt(np.mean(window**2))
        assert rms > 0.01 if audible else rms < 0.001
