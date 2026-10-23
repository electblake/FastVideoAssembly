# FastVideoAssembly

Native PySide6 application for arranging portrait videos into three timelines
and rendering them side by side. Separate application, settings, entry point,
Explorer registration, and Windows installer from FastVideoCropper.

## Run

Install Python 3.12+, uv, and FFmpeg/FFprobe on PATH, then:

```powershell
uv sync --locked
uv run fastvideoassembly
```

Open a folder with Ctrl+O, drop files/folders onto the window, or pass paths to
`uv run fastvideoassembly "C:\Videos"`. Imports include immediate MP4, MKV, MOV,
AVI and WebM files, without recursion or duplicates. Importing adds to the
library and rebuilds the balanced arrangement. Clear assembly starts over.

Only display aspect ratios below 1 enter the tracks; square and landscape clips
remain visible in the source library as excluded. Rotation metadata and sample
aspect ratio are considered. Longest clips are allocated to the currently
shortest column, then each column is sorted shortest to longest. This is a
duration-balancing heuristic, not a promise of an optimal equal partition.

The central timeline uses a shared seconds axis and duration-scaled blocks.
Click a block or list entry to select it. Move earlier/later changes playback
order; move left/right transfers the clip to the end of an adjacent column.
Balance restores automatic ordering. Double-click a clip to open its source.
All three columns must contain a clip before rendering is enabled.

Output is silent H.264 MP4, 1920×1080 at 30 fps. Each column is 640×1080.
Videos are fitted with black padding, without cropping or stretching. The
shorter columns hold their final frame until the longest finishes. Choose a new
output filename: FFmpeg refuses to overwrite existing files. Stop rendering
sends FFmpeg its normal quit command and retains the partial output. Diagnostics
and the raw process exit code remain visible; there are no alternate encoders,
retries, or fallback formats. This initial renderer opens all selected clips in
one FFmpeg composition, so resource use grows with the number of inputs.

Settings → Appearance offers the same qt-themes palettes and icon variants as
FastVideoCropper. QSettings stores preferences, geometry, dock positions and
splitter sizes in platformdirs' FastVideoAssembly `settings.ini`. Clip ordering
is session-only. Help → Install in File Explorer registers separate per-user
FastVideoAssembly menu entries.

Reused foundation: Qt Widgets, qt-themes, PyQtGraph, platformdirs, component QSS,
icon assets, Explorer integration, and pinned online installer downloads.
Crop/ROI controls, segment detection, crop export, GPU probing, automatic power
actions and Cropper's update feed are omitted. No dependency on the Cropper
checkout is required at runtime.

```powershell
uv run pytest
uv run ruff check .
```

See [Windows installer](packaging/README.md).
