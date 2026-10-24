"""Audio normalization filters and true-peak measurement passes."""

import math


def normalization_filter(mode, peak=None, gain=None):
    if gain is not None:
        return f"volume={gain}dB:precision=double,aresample=48000"
    if mode == "None":
        return "anull"
    if mode == "True Peak":
        # Digital silence has no finite peak and must remain silence.
        gain = 0 if peak == -math.inf else -1.0 - peak
        return f"volume={gain}dB:precision=double,aresample=48000"
    return {"YouTube": "loudnorm=I=-14:TP=-1:LRA=50:linear=false,aresample=48000"}[mode]


def peak_measurement_arguments(clip):
    return [
        "-hide_banner",
        "-i",
        str(clip.path),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        (
            "aresample=48000:async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=duration={clip.duration},"
            "loudnorm=I=-14:TP=-1:LRA=50:linear=false:print_format=json"
        ),
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "null",
        "-",
    ]


def mix_peak_arguments(columns, duration):
    args = ["-hide_banner"]
    for path in columns:
        args += ["-i", str(path)]
    graph = ";".join(f"[{i}:a:0]asetpts=PTS-STARTPTS[a{i}]" for i in range(len(columns)))
    graph += (
        ";" + "".join(f"[a{i}]" for i in range(len(columns)))
        + f"amix=inputs={len(columns)}:duration=longest:dropout_transition=0:normalize=1,"
        f"atrim=duration={duration},"
        "loudnorm=I=-14:TP=-1:LRA=50:linear=false:print_format=json[audio]"
    )
    return args + [
        "-filter_complex",
        graph,
        "-map",
        "[audio]",
        "-vn",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "null",
        "-",
    ]
