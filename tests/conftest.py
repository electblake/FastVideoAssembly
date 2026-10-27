import json
import subprocess

import pytest

from fastvideoassembly import app


@pytest.fixture(autouse=True)
def isolated_launch(request, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "user_config_path", lambda *args, **kwargs: tmp_path)
    initialize = app.Application.__init__

    def initialize_test(self, *args, **kwargs):
        kwargs.setdefault(
            "no_profile", request.node.get_closest_marker("profile") is None
        )
        kwargs.setdefault("minimize", True)
        initialize(self, *args, **kwargs)

    monkeypatch.setattr(app.Application, "__init__", initialize_test)


@pytest.fixture
def controller(qtbot):
    controller = app.Application()
    qtbot.addWidget(controller.window)
    controller.window.show()
    return controller


@pytest.fixture(scope="session")
def preview_source(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("media")
    source = tmp_path / "preview.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=60x120:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    return source


@pytest.fixture
def measure():
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

    return measure
