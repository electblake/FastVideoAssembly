"""Video metadata, balanced ordering, and the three-column FFmpeg composition."""

from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


@dataclass(frozen=True)
class Clip:
    path: Path
    duration: float
    width: float
    height: float

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
    stream = metadata["streams"][0]
    width, height = stream["width"], stream["height"]
    if "sample_aspect_ratio" in stream and ":" in stream["sample_aspect_ratio"]:
        numerator, denominator = map(int, stream["sample_aspect_ratio"].split(":"))
        if numerator:
            width *= numerator / denominator
    if "side_data_list" in stream:
        for data in stream["side_data_list"]:
            if "rotation" in data and round(data["rotation"] / 90) % 2:
                width, height = height, width
    return Clip(Path(path), float(metadata["format"]["duration"]), width, height)


def balance(clips):
    """Longest-first allocation balances totals; each track plays shortest-first."""
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
    return tracks


def track_durations(tracks):
    return [sum(clip.duration for clip in track) for track in tracks]


def export_arguments(tracks, output, graph_path, height=1080, column_width=640):
    """Fit, concatenate, extend the last frames, and stack three equal columns."""
    args = ["-hide_banner", "-n"]
    filters = []
    index = 0
    for column, track in enumerate(tracks):
        labels = []
        for clip in track:
            args += ["-i", str(clip.path)]
            label = f"clip{index}"
            filters.append(
                f"[{index}:v:0]setpts=PTS-STARTPTS,"
                "scale=iw*sar:ih,setsar=1,"
                f"scale={column_width}:{height}:force_original_aspect_ratio=decrease:"
                "force_divisible_by=2,"
                f"pad={column_width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                f"fps=30,format=yuv420p,setsar=1[{label}]"
            )
            labels.append(f"[{label}]")
            index += 1
        filters.append(
            "".join(labels)
            + f"concat=n={len(track)}:v=1:a=0,"
            + f"tpad=stop_mode=clone:stop=-1[column{column}]"
        )
    filters.append("[column0][column1][column2]hstack=inputs=3[output]")
    Path(graph_path).write_text(";\n".join(filters), encoding="utf-8")
    args += [
        "-filter_complex_script",
        str(graph_path),
        "-map",
        "[output]",
        "-t",
        str(max(track_durations(tracks))),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]
    return args
