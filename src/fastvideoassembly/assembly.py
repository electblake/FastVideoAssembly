"""Video metadata, balanced ordering, and the three-column FFmpeg composition."""

from dataclasses import dataclass
from fractions import Fraction
from functools import partial
from math import ceil
from pathlib import Path

from .audio import normalization_filter

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


@dataclass(frozen=True)
class Clip:
    path: Path
    duration: float
    width: float
    height: float
    has_audio: bool = False

    @property
    def portrait(self):
        return self.width / self.height < 1


def video_paths(inputs):
    paths = []
    for source in inputs:
        source = Path(source).resolve()
        entries = sorted(source.iterdir()) if source.is_dir() else [source]
        for path in entries:
            if (
                path.is_file()
                and path.suffix.lower() in VIDEO_EXTENSIONS
                and path not in paths
            ):
                paths.append(path)
    return paths


def clip_from_probe(path, metadata):
    stream = next(
        stream for stream in metadata["streams"] if stream["codec_type"] == "video"
    )
    width, height = stream["width"], stream["height"]
    if "sample_aspect_ratio" in stream and ":" in stream["sample_aspect_ratio"]:
        numerator, denominator = map(int, stream["sample_aspect_ratio"].split(":"))
        if numerator:
            width *= numerator / denominator
    if "side_data_list" in stream:
        for data in stream["side_data_list"]:
            if "rotation" in data and round(data["rotation"] / 90) % 2:
                width, height = height, width
    return Clip(
        Path(path),
        float(metadata["format"]["duration"]),
        width,
        height,
        any(stream["codec_type"] == "audio" for stream in metadata["streams"]),
    )


def balance(clips, mixed=False):
    """Balance track totals, then order ascending or alternate long/short clips."""
    tracks = [[], [], []]
    durations = [0.0, 0.0, 0.0]
    for clip in sorted(
        (clip for clip in clips if clip.portrait),
        key=lambda clip: (-clip.duration, str(clip.path)),
    ):
        index = min(range(3), key=lambda index: durations[index])
        tracks[index].append(clip)
        durations[index] += clip.duration
    for track in tracks:
        track.sort(key=lambda clip: (clip.duration, str(clip.path)))
        if mixed:
            remaining = list(track)
            track.clear()
            # Pair opposite duration ranks so short and long clips are spread
            # through the timeline instead of forming separate runs.
            while remaining:
                track.append(remaining.pop())
                if remaining:
                    track.append(remaining.pop(0))
    return tracks


def track_durations(tracks):
    return [sum(clip.duration for clip in track) for track in tracks]


@dataclass(frozen=True)
class RenderConfig:
    column_width: int = 640
    height: int = 1080
    fps: str = "30"
    encoder: str = "hevc_nvenc"
    speed: str = "balanced"
    quality: int = 20
    normalization: str = "None"
    audio_codec: str = "aac"

    @property
    def pixel_format(self):
        return "yuv420p10le" if self.encoder == "hevc_nvenc" else "yuv420p"

    def encoding_arguments(self):
        args = [
            "-c:v",
            self.encoder,
            "-c:a",
            self.audio_codec,
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
        ]
        if self.encoder == "libx264":
            preset = {"fast": "veryfast", "balanced": "medium", "quality": "slow"}[
                self.speed
            ]
            args += ["-preset", preset, "-crf", str(self.quality)]
        else:
            preset = {"fast": "p2", "balanced": "p4", "quality": "p6"}[self.speed]
            args += [
                "-preset",
                preset,
                "-tune",
                "hq",
                "-rc",
                "vbr",
                "-cq",
                str(self.quality),
                "-b:v",
                "0",
            ]
        if self.encoder == "hevc_nvenc":
            args += ["-profile:v", "main10", "-tag:v", "hvc1"]
        encoder_format = "p010le" if self.encoder == "hevc_nvenc" else self.pixel_format
        return args + [
            "-pix_fmt",
            encoder_format,
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
        ]


def clip_duration(clip, config):
    """Align cuts to output frames so audio and video share each boundary."""
    rate = Fraction(config.fps)
    return float(ceil(Fraction(str(clip.duration)) * rate) / rate)


def clip_arguments(clip, output, graph_path, config, peaks=None):
    """Encode a single center-filled clip with continuous, uncompressed audio."""
    duration = clip_duration(clip, config)
    filters = [
        (
            "[0:v:0]"
            f"scale={config.column_width}:{config.height}:force_original_aspect_ratio=increase:"
            "force_divisible_by=2:reset_sar=1,"
            f"crop={config.column_width}:{config.height}:(iw-ow)/2:(ih-oh)/2,"
            f"fps={config.fps}:start_time=0,format={config.pixel_format},setsar=1,"
            f"tpad=stop_mode=clone:stop=-1,trim=duration={duration}[output]"
        )
    ]
    if clip.has_audio:
        peak = peaks[clip.path] if config.normalization == "True Peak" else None
        normalize = normalization_filter(config.normalization, peak)
        filters.append(
            "[0:a:0]aresample=48000:async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=duration={clip.duration},{normalize},"
            f"apad,atrim=duration={duration}[audio]"
        )
    else:
        filters.append(
            "anullsrc=r=48000:cl=stereo,"
            f"atrim=duration={duration},asetpts=PTS-STARTPTS[audio]"
        )
    Path(graph_path).write_text(";\n".join(filters), encoding="utf-8")
    return (
        [
            "-hide_banner",
            "-n",
            "-i",
            str(clip.path),
            "-/filter_complex",
            str(graph_path),
            "-map",
            "[output]",
            "-map",
            "[audio]",
        ]
        + config.encoding_arguments()
        + ["-c:a", "pcm_s24le", str(output)]
    )


def column_jobs(track, output, manifest, config, peaks=None):
    """Render clips sequentially, then copy their video into an A/B/C output."""
    manifest = Path(manifest)
    lines = ["ffconcat version 1.0"]
    for index, clip in enumerate(track):
        segment = manifest.with_name(f"{manifest.stem}-{index}.mov")
        duration = clip_duration(clip, config)
        lines += [f"file '{segment.name}'", f"duration {duration:.9f}"]
        yield (
            segment,
            duration,
            partial(
                clip_arguments,
                clip,
                segment,
                segment.with_suffix(".ffgraph"),
                config,
                peaks,
            ),
        )
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args = [
        "-hide_banner",
        "-n",
        "-f",
        "concat",
        "-i",
        str(manifest),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-af",
        "aresample=48000:async=1:first_pts=0",
        "-c:a",
        config.audio_codec,
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]
    yield output, sum(clip_duration(clip, config) for clip in track), args


def composition_arguments(columns, duration, output, graph_path, config, peak=None):
    """Stack already normalized columns; preserve their shared render settings."""
    args = ["-hide_banner", "-n"]
    filters = []
    for index, path in enumerate(columns):
        args += ["-i", str(path)]
        filters.append(
            f"[{index}:v:0]setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop=-1[column{index}]"
        )
        filters.append(f"[{index}:a:0]asetpts=PTS-STARTPTS[audio{index}]")
    filters.append("[column0][column1][column2]hstack=inputs=3[output]")
    filters.append(
        "[audio0][audio1][audio2]amix=inputs=3:duration=longest:"
        f"dropout_transition=0:normalize=1,atrim=duration={duration},"
        f"{normalization_filter(config.normalization, peak)},apad[audio]"
    )
    Path(graph_path).write_text(";\n".join(filters), encoding="utf-8")
    return (
        args
        + [
            "-/filter_complex",
            str(graph_path),
            "-map",
            "[output]",
            "-map",
            "[audio]",
            "-t",
            str(duration),
        ]
        + config.encoding_arguments()
        + [str(output)]
    )
