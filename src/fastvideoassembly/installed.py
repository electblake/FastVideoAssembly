"""Entry point using Windows Setup's private FFmpeg installation."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import APP_NAME, APP_VERSION, integrations
from .app import Application

MODULE = "fastvideoassembly.installed"


def main():
    if sys.argv[1:] == ["--install-explorer"]:
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
        paths=sys.argv[1:],
        launcher_module=MODULE,
    )
    controller.window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
