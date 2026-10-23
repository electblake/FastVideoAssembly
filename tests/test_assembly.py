import json
import subprocess
from pathlib import Path

import pytest

from fastvideoassembly.assembly import (
    Clip,
    balance,
    clip_from_probe,
    export_arguments,
    track_durations,
    video_paths,
)


def test_balanced_tracks_keep_every_portrait_once_and_ascending():
    clips = [Clip(Path(f"{n}.mp4"), n, 90, 160) for n in range(1, 10)]
    clips += [Clip(Path("wide.mp4"), 10, 160, 90), Clip(Path("square.mp4"), 2, 90, 90)]
    tracks = balance(clips)
    assert sorted(clip.duration for track in tracks for clip in track) == list(
        range(1, 10)
    )
    assert track_durations(tracks) == [16, 15, 14]
    assert all(
        track == sorted(track, key=lambda clip: clip.duration) for track in tracks
    )


def test_metadata_uses_rotation_and_pixel_aspect_ratio():
    metadata = {
        "streams": [
            {
                "width": 160,
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
    metadata["streams"][0] = {"width": 90, "height": 160, "sample_aspect_ratio": "2:1"}
    assert not clip_from_probe(Path("anamorphic.mp4"), metadata).portrait


def test_folder_inputs_are_nonrecursive_and_deduplicated(tmp_path):
    video = tmp_path / "one.MP4"
    video.touch()
    (tmp_path / "notes.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "two.mp4").touch()
    assert video_paths([tmp_path, video]) == [video]


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


def test_render_column_positions_order_padding_and_final_frame_hold(media, tmp_path):
    red, green, blue, yellow = media
    tracks = [[red, yellow], [green], [blue]]
    output = tmp_path / "assembled.mp4"
    args = export_arguments(
        tracks, output, tmp_path / "graph.txt", height=120, column_width=64
    )
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
    assert len(metadata["streams"]) == 1
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
        for x, expected in [(32, expected_left), (96, (0, 255, 0)), (160, (0, 0, 255))]:
            pixel = frame[(60 * 192 + x) * 3 : (60 * 192 + x) * 3 + 3]
            assert tuple(pixel) == pytest.approx(expected, abs=15)
    # FFmpeg's -n protects source files and existing outputs directly.
    existing = output.read_bytes()
    second = subprocess.run(["ffmpeg", *args], check=False, capture_output=True)
    assert b"already exists" in second.stderr
    assert output.read_bytes() == existing


def test_gui_import_and_full_resolution_export(media, tmp_path, qtbot, monkeypatch):
    from fastvideoassembly import app

    monkeypatch.setattr(
        app, "user_config_path", lambda *args, **kwargs: tmp_path / "settings"
    )
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.window.show()
    controller.add_paths([clip.path for clip in media])
    qtbot.waitUntil(lambda: not controller.loading, timeout=30000)
    assert len(controller.clips) == 4
    assert controller.export_button.isEnabled()
    output = tmp_path / "gui-output.mp4"
    controller.start_export(output)
    assert not controller.balance_button.isEnabled()
    qtbot.waitUntil(lambda: not controller.running, timeout=60000)
    assert controller.process.exitCode() == 0
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    assert (stream["width"], stream["height"]) == (1920, 1080)
    assert controller.progress.value() > 900
