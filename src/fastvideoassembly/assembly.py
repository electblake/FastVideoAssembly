"""Video metadata, balanced ordering, and the column FFmpeg composition."""

from dataclasses import dataclass
from fractions import Fraction
from math import ceil
from pathlib import Path

from .audio import normalization_filter

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}


@dataclass(frozen=True)
class Source:
    path: Path


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


def timeline_name(index):
    name = ""
    index += 1
    while index:
        index, letter = divmod(index - 1, 26)
        name = chr(65 + letter) + name
    return name


def balance(clips, longest_first=False, track_count=3):
    """Balance track totals, then sort clips by duration in the requested direction."""
    tracks = [[] for _ in range(track_count)]
    durations = [0.0] * track_count
    for clip in sorted(
        clips,
        key=lambda clip: (-clip.duration, str(clip.path)),
    ):
        index = min(range(track_count), key=lambda index: durations[index])
        tracks[index].append(clip)
        durations[index] += clip.duration
    for track in tracks:
        track.sort(
            key=lambda clip: (
                -clip.duration if longest_first else clip.duration,
                str(clip.path),
            )
        )
    return tracks


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
    filter_threads: int = 4
    decoder: str = "none"
    scaler: str = "cpu"
    scaling_algorithm: str = "bicubic"
    qsv_scaling_mode: str = "hq"

    @property
    def pixel_format(self):
        return "yuv420p10le" if self.encoder == "hevc_nvenc" else "yuv420p"

    @property
    def hardware_pixel_format(self):
        return "p010le" if self.encoder == "hevc_nvenc" else "nv12"

    def hardware_arguments(self, scaling=False):
        args = []
        if self.decoder == "qsv" or (scaling and self.scaler == "qsv"):
            args += ["-init_hw_device", "qsv=intel:hw,child_device_type=d3d11va"]
        if scaling and self.scaler != "cpu":
            if self.scaler == "qsv":
                device = "intel"
            else:
                device = "scaler"
                args += ["-init_hw_device", "cuda=scaler:0"]
            args += ["-filter_hw_device", device]
        return args

    def decoding_arguments(self, scaling=False):
        args = ["-hwaccel", self.decoder]
        if self.decoder == "qsv":
            args += ["-hwaccel_device", "intel", "-hwaccel_output_format", "qsv"]
        elif self.decoder == "cuda" and scaling and self.scaler == "cuda":
            args += ["-hwaccel_device", "scaler", "-hwaccel_output_format", "cuda"]
        return args

    def decoded_frames_filter(self, scaling=False):
        if self.decoder == "qsv" and not (scaling and self.scaler == "qsv"):
            return (f"vpp_qsv=format={self.hardware_pixel_format},"
                    f"hwdownload,format={self.hardware_pixel_format},")
        return ""

    def scaling_filter(self):
        width, height = self.column_width, self.height
        if self.scaler == "cpu":
            algorithm = {"nearest": "neighbor", "bilinear": "bilinear",
                         "bicubic": "bicubic", "lanczos": "lanczos"}[self.scaling_algorithm]
            return (f"scale={width}:{height}:force_original_aspect_ratio=increase:"
                    f"force_divisible_by=2:reset_sar=1:flags={algorithm},")
        upload = ""
        if (self.decoder, self.scaler) not in (("cuda", "cuda"), ("qsv", "qsv")):
            upload = f"format={self.hardware_pixel_format},hwupload,"
        dimensions = (f"'ceil(max({width},{height}*dar)/2)*2':"
                      f"'ceil(max({height},{width}/dar)/2)*2'")
        options = {"cuda": f":interp_algo={self.scaling_algorithm}",
                   "qsv": f":mode={self.qsv_scaling_mode}"}[self.scaler]
        return (f"{upload}scale_{self.scaler}={dimensions}:format={self.hardware_pixel_format}{options},"
                f"hwdownload,format={self.hardware_pixel_format},setsar=1,")

    def encoding_arguments(self):
        args = ["-c:v", self.encoder]
        if self.audio_codec == "none":
            args += ["-an"]
        else:
            args += ["-c:a", self.audio_codec, "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        if self.encoder == "libx264":
            preset = {
                "fastest": "ultrafast",
                "fast": "veryfast",
                "fast_medium": "fast",
                "balanced": "medium",
                "slow": "slow",
                "quality": "slower",
                "slowest": "veryslow",
            }[self.speed]
            args += ["-preset", preset, "-crf", str(self.quality)]
        else:
            preset = {
                "fastest": "p1",
                "fast": "p2",
                "fast_medium": "p3",
                "balanced": "p4",
                "slow": "p5",
                "quality": "p6",
                "slowest": "p7",
            }[self.speed]
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


def column_arguments(track, output, graph_path, config, peaks=None):
    """Encode a complete timeline directly from its original sources."""
    args = ["-hide_banner", "-n", "-filter_complex_threads", str(config.filter_threads)]
    args += config.hardware_arguments(scaling=True)
    filters = []
    inputs = []
    for index, clip in enumerate(track):
        duration = clip_duration(clip, config)
        args += config.decoding_arguments(scaling=True)
        args += ["-threads", "1", "-t", str(duration), "-i", str(clip.path)]
        filters.append(
            f"[{index}:v:0]setpts=PTS-STARTPTS,"
            f"{config.decoded_frames_filter(scaling=True)}{config.scaling_filter()}"
            f"crop={config.column_width}:{config.height}:(iw-ow)/2:(ih-oh)/2,"
            f"fps={config.fps}:start_time=0,format={config.pixel_format},setsar=1,"
            f"tpad=stop_mode=clone:stop=-1,trim=duration={duration},"
            f"setpts=PTS-STARTPTS[v{index}]"
        )
        inputs.append(f"[v{index}]")
        if config.audio_codec != "none":
            if clip.has_audio:
                peak = peaks[clip.path] if config.normalization == "True Peak" else None
                normalize = normalization_filter(config.normalization, peak)
                filters.append(
                    f"[{index}:a:0]aresample=48000:async=1:first_pts=0,"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"atrim=duration={clip.duration},{normalize},"
                    f"apad,atrim=duration={duration},asetpts=PTS-STARTPTS[a{index}]"
                )
            else:
                filters.append(
                    "anullsrc=r=48000:cl=stereo,"
                    f"atrim=duration={duration},asetpts=PTS-STARTPTS[a{index}]"
                )
            inputs.append(f"[a{index}]")
    audio = config.audio_codec != "none"
    filters.append(
        "".join(inputs) + f"concat=n={len(track)}:v=1:a={int(audio)}[output]"
        + ("[audio]" if audio else "")
    )
    Path(graph_path).write_text(";\n".join(filters), encoding="utf-8")
    return (
        args + ["-/filter_complex", str(graph_path), "-map", "[output]"]
        + (["-map", "[audio]"] if audio else [])
        + config.encoding_arguments()
        + [str(output)]
    )


def composition_arguments(columns, duration, output, graph_path, config, peak=None):
    """Stack already normalized columns; preserve their shared render settings."""
    args = ["-hide_banner", "-n", "-filter_complex_threads", str(config.filter_threads)]
    args += config.hardware_arguments()
    filters = []
    for index, path in enumerate(columns):
        args += config.decoding_arguments() + ["-i", str(path)]
        filters.append(
            f"[{index}:v:0]{config.decoded_frames_filter()}"
            f"setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop=-1[column{index}]"
        )
        if config.audio_codec != "none":
            filters.append(f"[{index}:a:0]asetpts=PTS-STARTPTS[audio{index}]")
    filters.append("".join(f"[column{i}]" for i in range(len(columns))) + f"hstack=inputs={len(columns)}[output]")
    if config.audio_codec != "none":
        filters.append(
            "".join(f"[audio{i}]" for i in range(len(columns)))
            + f"amix=inputs={len(columns)}:duration=longest:"
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
            "-t",
            str(duration),
        ]
        + (["-map", "[audio]"] if config.audio_codec != "none" else [])
        + config.encoding_arguments()
        + [str(output)]
    )


def division_arguments(tracks, duration, output, graph_path, config, peaks, peak=None, measure=False):
    """Normalize source timelines and compose a division without intermediate media."""
    args = ["-hide_banner", "-n", "-filter_complex_threads", str(config.filter_threads)]
    if not measure:
        args += config.hardware_arguments(scaling=True)
    filters = []
    index = 0
    audio = config.audio_codec != "none"
    for column, track in enumerate(tracks):
        inputs = []
        for clip in track:
            length = clip_duration(clip, config)
            if not measure:
                args += config.decoding_arguments(scaling=True)
            args += ["-threads", "1", "-t", str(length), "-i", str(clip.path)]
            if not measure:
                filters.append(
                    f"[{index}:v:0]setpts=PTS-STARTPTS,"
                    f"{config.decoded_frames_filter(scaling=True)}{config.scaling_filter()}"
                    f"crop={config.column_width}:{config.height}:(iw-ow)/2:(ih-oh)/2,"
                    f"fps={config.fps}:start_time=0,format={config.pixel_format},setsar=1,"
                    f"tpad=stop_mode=clone:stop_duration={length},trim=duration={length},"
                    f"setpts=PTS-STARTPTS[v{index}]"
                )
                inputs.append(f"[v{index}]")
            if audio:
                if clip.has_audio:
                    source_peak = peaks[clip.path] if config.normalization == "True Peak" else None
                    filters.append(
                        f"[{index}:a:0]aresample=48000:async=1:first_pts=0,"
                        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
                        f"atrim=duration={clip.duration},{normalization_filter(config.normalization, source_peak)},"
                        f"apad=whole_dur={length},atrim=duration={length},asetpts=PTS-STARTPTS[a{index}]"
                    )
                else:
                    filters.append(
                        "anullsrc=r=48000:cl=stereo,"
                        f"atrim=duration={length},asetpts=PTS-STARTPTS[a{index}]"
                    )
                inputs.append(f"[a{index}]")
            index += 1
        filters.append(
            "".join(inputs) + f"concat=n={len(track)}:v={int(not measure)}:a={int(audio)}"
            + (f"[vcolumn{column}]" if not measure else "")
            + (f"[acolumn{column}]" if audio else "")
        )
        if not measure:
            # Concat uses microsecond timestamps; align columns to a shared frame clock.
            filters.append(
                f"[vcolumn{column}]fps={config.fps}:start_time=0,"
                f"tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration}[column{column}]"
            )
    if not measure:
        filters.append("".join(f"[column{i}]" for i in range(len(tracks)))
                       + f"hstack=inputs={len(tracks)}[output]")
    if audio:
        normalize = ("loudnorm=I=-14:TP=-1:LRA=50:linear=false:print_format=json" if measure
                     else normalization_filter(config.normalization, peak))
        filters.append(
            "".join(f"[acolumn{i}]" for i in range(len(tracks)))
            + f"amix=inputs={len(tracks)}:duration=longest:dropout_transition=0:normalize=1,"
            f"atrim=duration={duration},{normalize}"
            + ("[audio]" if measure else f",apad=whole_dur={duration},atrim=duration={duration}[audio]")
        )
    Path(graph_path).write_text(";\n".join(filters), encoding="utf-8")
    args += ["-/filter_complex", str(graph_path)]
    if measure:
        return args + ["-map", "[audio]", "-vn", "-progress", "pipe:1", "-nostats", "-f", "null", "-"]
    return (args + ["-map", "[output]", "-t", str(duration)]
            + (["-map", "[audio]"] if audio else [])
            + config.encoding_arguments() + [str(output)])
