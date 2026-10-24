import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

from fastvideoassembly import hardware
from fastvideoassembly.assembly import Clip, RenderConfig, column_arguments


def test_render_hardware_intersects_gpu_vendors_and_ffmpeg_capabilities(monkeypatch):
    run = Mock(side_effect=[
        SimpleNamespace(stdout=json.dumps(["NVIDIA", "Intel Corporation"])),
        SimpleNamespace(stdout="cuda qsv d3d11va dxva2"),
        SimpleNamespace(stdout="scale_cuda scale_qsv vpp_qsv"),
    ])
    monkeypatch.setattr(hardware.subprocess, "run", run)
    decoders, scalers = hardware.render_hardware("test-supported-ffmpeg")
    assert [value for _, value in decoders] == ["none", "cuda", "qsv", "d3d11va", "dxva2"]
    assert [value for _, value in scalers] == ["cpu", "cuda", "qsv"]


def test_render_hardware_omits_backends_without_matching_gpu_or_filters(monkeypatch):
    run = Mock(side_effect=[
        SimpleNamespace(stdout=json.dumps(["Intel Corporation"])),
        SimpleNamespace(stdout="cuda qsv d3d11va dxva2"),
        SimpleNamespace(stdout="scale_cuda vpp_qsv"),
    ])
    monkeypatch.setattr(hardware.subprocess, "run", run)
    decoders, scalers = hardware.render_hardware("test-limited-ffmpeg")
    assert [value for _, value in decoders] == ["none", "qsv", "d3d11va", "dxva2"]
    assert scalers == [("CPU", "cpu")]


def test_available_scalers_preserve_anamorphic_center_crop(tmp_path):
    source = tmp_path / "anamorphic.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "color=red:s=320x240:r=24:d=0.25,drawbox=x=120:y=0:w=80:h=240:color=lime:t=fill,setsar=2",
        "-c:v", "libx264", str(source),
    ], check=True, capture_output=True)
    _, scalers = hardware.render_hardware("ffmpeg")
    for _, scaler in scalers:
        output = tmp_path / f"{scaler}.mp4"
        config = RenderConfig(column_width=160, height=240, encoder="libx264",
                              scaler=scaler, audio_codec="none")
        args = column_arguments([Clip(source, 0.25, 640, 240)], output,
                                tmp_path / f"{scaler}.txt", config)
        subprocess.run(["ffmpeg", *args], check=True, capture_output=True)
        frame = subprocess.run([
            "ffmpeg", "-v", "error", "-i", str(output), "-frames:v", "1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ], check=True, capture_output=True).stdout
        assert len(frame) == 160 * 240 * 3
        for x in (8, 80, 151):
            offset = (120 * 160 + x) * 3
            red, green, blue = frame[offset:offset + 3]
            assert green > 220 and red < 25 and blue < 25, scaler
        metadata = json.loads(subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=sample_aspect_ratio", "-of", "json", str(output),
        ], check=True, capture_output=True, text=True).stdout)
        assert metadata["streams"][0]["sample_aspect_ratio"] == "1:1", scaler
