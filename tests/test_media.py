import json
import math
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

from fastvideoassembly.assembly import (
    Clip,
    RenderConfig,
    balance,
    clip_duration,
    clip_from_probe,
    division_arguments,
    video_paths,
)
from fastvideoassembly.audio import normalization_filter, peak_measurement_arguments
from fastvideoassembly.timeline import clip_spans, move_clips


def test_source_metadata_and_balancing(tmp_path):
    clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 10)]
    tracks = balance(clips)
    assert sorted(clip.duration for track in tracks for clip in track) == list(
        range(1, 10)
    )
    assert [sum(clip.duration for clip in track) for track in tracks] == [16, 15, 14]
    assert all(
        track == sorted(track, key=lambda clip: clip.duration) for track in tracks
    )

    clips = [
        Clip(Path(f"clip{i}.mp4"), i + 1, width, height)
        for i, (width, height) in enumerate([(60, 120), (120, 60), (120, 120)])
    ]
    assert {clip for track in balance(clips) for clip in track} == set(clips)

    clips = [
        Clip(Path(f"{n}.mp4"), n, 90, 160) for n in [1, 1, 3, 5, 8, 40, 600, 1200, 1975]
    ]
    ascending = balance(clips)
    descending = balance(clips, longest_first=True)
    for original, ordered in zip(ascending, descending):
        assert sum(clip.duration for clip in ordered) == sum(
            clip.duration for clip in original
        )
        assert sorted(c.path for c in ordered) == sorted(c.path for c in original)
        durations = [clip.duration for clip in ordered]
        assert durations == sorted(durations, reverse=True)
    assert balance(clips, longest_first=True) == descending
    assert balance([], longest_first=True) == [[], [], []]

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

    video = tmp_path / "one.MP4"
    video.touch()
    (tmp_path / "notes.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "two.mp4").touch()
    assert video_paths([tmp_path, video]) == [video]


def test_timeline_moves_preserve_order_and_duration():
    fps = "30000/1001"
    for mask in (1, 5, 31):
        config = RenderConfig(fps=fps)
        track = [
            Clip(Path(f"{i}.mp4"), duration, 60, 120)
            for i, duration in enumerate([7.11, 0.101, 20.01, 2.1, 13.2])
        ]
        original = track[:]
        selected = {clip for i, clip in enumerate(track) if mask & (1 << i)}
        moved = [clip for clip in track if clip in selected]
        remaining = [clip for clip in track if clip not in selected]
        total = sum(clip_duration(clip, config) for clip in track)
        remaining_end = sum(clip_duration(clip, config) for clip in remaining)
        targets = ["start", "end", "backward", "forward", 0.0, total, total + 5]
        for start, end, _clip in clip_spans(track, config):
            targets.extend([start, (start + end) / 2, end])
        for target in targets:
            result, position = move_clips(track, selected, target, config)
            assert track == original
            assert len(result) == len(track)
            assert set(result) == set(track)
            assert [clip for clip in result if clip not in selected] == remaining
            index = result.index(moved[0])
            assert result[index : index + len(moved)] == moved
            spans = list(clip_spans(result, config))
            assert spans[0][0] == 0
            assert spans[-1][1] == pytest.approx(total)
            assert all(left[1] == right[0] for left, right in pairwise(spans))
            assert spans[index][0] == pytest.approx(position)
            if isinstance(target, float):
                assert position >= min(target, remaining_end)
                if index:
                    assert spans[index - 1][0] < target
            elif target == "start":
                assert index == 0
            elif target == "end":
                assert index == len(remaining)

    track = [Clip(Path(f"{i}.mp4"), 10, 60, 120) for i in range(5)]
    result, position = move_clips(track, {track[0]}, 15.0, RenderConfig())
    assert result == [track[1], track[2], track[0], track[3], track[4]]
    assert position == 20
    result, position = move_clips(track, {track[0], track[2]}, 15.0, RenderConfig())
    assert result == [track[1], track[3], track[0], track[2], track[4]]
    assert position == 20

    track = [Clip(Path(f"{i}.mp4"), 10, 60, 120) for i in range(4)]
    for target, expected in [
        (0.0, 0),
        (0.1, 10),
        (9.9, 10),
        (10.0, 10),
        (10.1, 20),
        (35.0, 30),
    ]:
        _result, position = move_clips(track, {track[-1]}, target, RenderConfig())
        assert position == expected


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
    args = division_arguments(tracks, 1.2, output, tmp_path / "graph.txt", config, {})
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
    existing = output.read_bytes()
    second = subprocess.run(["ffmpeg", *args], check=False, capture_output=True)
    assert b"already exists" in second.stderr
    assert output.read_bytes() == existing


def test_normalization_levels_and_silence(tmp_path, measure):
    mode = "True Peak"
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
        else:
            assert float(result["input_tp"]) == pytest.approx(-1, abs=0.1)
        levels.append(float(result["input_i"]))
    assert abs(levels[0] - levels[1]) < 0.3
