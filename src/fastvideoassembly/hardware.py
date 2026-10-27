"""Windows GPU and FFmpeg capabilities used by the render controls."""

import json
import subprocess
from functools import cache, partial

import ffmpeg.ffmpeg as ffmpeg_api
from ffmpeg import FFmpeg

ffmpeg_api.create_subprocess = partial(
    ffmpeg_api.create_subprocess,
    startupinfo=subprocess.STARTUPINFO(
        dwFlags=subprocess.STARTF_USESHOWWINDOW, wShowWindow=subprocess.SW_HIDE,
    ),
)


@cache
def render_hardware(ffmpeg):
    adapters = json.loads(subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference = 'Stop'; ConvertTo-Json -InputObject @(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty AdapterCompatibility)"],
        check=True, capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout)
    accelerators = FFmpeg(ffmpeg).option("hide_banner").option("hwaccels").execute().decode().split()
    filters = FFmpeg(ffmpeg).option("hide_banner").option("filters").execute().decode().split()
    decoders = [("CPU", "none")]
    scalers = [("CPU", "cpu")]
    if "cuda" in accelerators and any("NVIDIA" in adapter.upper() for adapter in adapters):
        decoders.append(("NVIDIA NVDEC", "cuda"))
        if "scale_cuda" in filters:
            scalers.append(("NVIDIA CUDA", "cuda"))
    if any("INTEL" in adapter.upper() for adapter in adapters):
        if "qsv" in accelerators and "vpp_qsv" in filters:
            decoders.append(("Intel Quick Sync", "qsv"))
        if "qsv" in accelerators and "scale_qsv" in filters:
            scalers.append(("Intel Quick Sync", "qsv"))
    if adapters:
        for label, backend in (("Windows D3D11", "d3d11va"), ("Windows DXVA2", "dxva2")):
            if backend in accelerators:
                decoders.append((label, backend))
    return decoders, scalers
