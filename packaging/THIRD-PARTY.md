# Third-party components

Setup downloads uv and Python from Astral's GitHub releases and FFmpeg/FFprobe
from Gyan Doshi. Their pinned versions, URLs and checksums are recorded in
`uv.json`, `python.json`, and `vendor.json`. Setup does not embed their binaries.

Inno extracts Astral's python-build-standalone distribution. uv installs the
runtime wheels recorded in `uv.lock`: PySide6/Qt, Shiboken, NumPy, PyQtGraph,
platformdirs, qt-themes, python-ffmpeg, pyee and pywin32. Their licenses are retained in the installed Python
and package distributions. Qt libraries remain dynamically linked.

FFmpeg 8.1.2 essentials is licensed under GPLv3. Its extracted archive retains
the distributor's LICENSE and README, including build and source references.

- uv (MIT or Apache-2.0): https://github.com/astral-sh/uv
- Python distributions: https://github.com/astral-sh/python-build-standalone
- FFmpeg distributor: https://www.gyan.dev/ffmpeg/builds/
- FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/n8.1.2
- Qt licensing: https://www.qt.io/licensing/
- PyQtGraph: https://github.com/pyqtgraph/pyqtgraph
- NumPy: https://numpy.org/
- platformdirs: https://github.com/tox-dev/platformdirs
- qt-themes (MIT): https://github.com/beatreichenbach/qt-themes
- python-ffmpeg (MIT): https://github.com/jonghwanhyeon/python-ffmpeg
- pyee (MIT): https://github.com/jfhbrook/pyee
- pywin32: https://github.com/mhammond/pywin32

