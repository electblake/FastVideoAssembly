"""Entry point using Windows Setup's private FFmpeg installation."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import APP_NAME, APP_VERSION, integrations
from .app import Application

MODULE = "fastvideoassembly.installed"


def main():
    no_profile = "-NoProfile" in sys.argv[1:]
    minimize = "-Minimize" in sys.argv[1:]
    paths = [arg for arg in sys.argv[1:] if arg not in ("-NoProfile", "-Minimize")]
    if paths == ["--install-explorer"]:
        return integrations.install(MODULE)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    root = Path(sys.prefix).parents[1]
    tools = root / "tools/ffmpeg/ffmpeg-8.1.2-essentials_build/bin"
    controller = Application(
        str(tools / "ffmpeg.exe"),
        str(tools / "ffprobe.exe"),
        paths=paths,
        launcher_module=MODULE,
        no_profile=no_profile,
        minimize=minimize,
    )
    controller.window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
