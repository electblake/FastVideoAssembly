# FastVideoAssembly

Native PySide6 application for arranging portrait videos into three timelines
and rendering them side by side. Separate application, settings, entry point,
Explorer registration, and Windows installer from FastVideoCropper.

## Run

Install Python 3.12+, uv, and FFmpeg/FFprobe 8+ on PATH, then:

```powershell
uv sync --locked
uv run fastvideoassembly
```

Use Add Videos or Ctrl+O to select videos and folders together, drop files/folders onto the source list or window, or pass paths to
`uv run fastvideoassembly "C:\Videos"`. Imports include immediate MP4, MKV, MOV,
AVI and WebM files, without recursion or duplicates. Importing adds to the
library without changing timelines. Click Create Timelines to build the arrangement;
Shortest First and Longest First explicitly rebuild and sort it. Clear assembly starts over.
The source list is saved when changed, alongside window state on close, and restored on the next launch.
Restoring sources reads their metadata again without creating timelines.

The shared source library lists filenames without assembler-specific labels or
filtering. The **3 Column Assembly** central tab accepts display aspect ratios
below 1; square and landscape clips remain available in the shared source library.
Rotation metadata and sample aspect ratio are considered. Longest clips are allocated to the currently
shortest column, then each column is sorted shortest to longest. This is a
duration-balancing heuristic, not a promise of an optimal equal partition.

All three-column editing and render controls live in that tab. Preview, render,
audio, and output settings remain shared docks. Progress appears directly above
the log inside the shared Process log dock, which opens when processing starts.

The central timeline uses a shared seconds axis and duration-scaled blocks,
including the same output-frame rounding used by rendering.
Click a block or list entry to select it. Move earlier/later changes playback
order; move left/right transfers the clip to the end of an adjacent column.
**Shortest First** sorts clips by ascending duration; **Longest First** sorts
by descending duration. Both buttons first redistribute all eligible source clips
to keep the three column totals similar; ordering does not change those totals.
The former Balanced ordering has been removed because alternating duration ranks
did not distribute clip lengths evenly over playback time.
Double-click a clip to open its source.
Selecting a source, central column-list entry, or timeline segment shares one
selection across these views. The dockable **Preview** above Render Settings
shows the selected source with Play/Pause, Stop, and a scrubber.
**Remove Selected Clip** removes the source and its timeline entries from the
assembly without deleting the file or reordering other clips. Use either sorting
button when you want to redistribute the remaining clips.
All three columns must contain a clip before rendering is enabled.

The **Render Settings** dock controls output dimensions (1080p or
2160p), frame rate, encoder, speed preset and quality. View can reopen the dock;
it can be moved or floated like the source and log panels. Settings persist and
remain fixed when importing videos. Defaults target the verified RTX 3090:
NVIDIA HEVC Main 10, Balanced/P4, CQ 20, 1920×1080 at 30 fps. NVIDIA H.264 and
CPU H.264 are explicit alternatives, never automatic substitutes. Lower quality
values produce larger, higher-quality files; NVENC CQ and CPU CRF are different
scales. Decoding, scaling, cropping and stacking currently run on the CPU;
NVENC accelerates encoding. No throughput optimum is claimed from the smoke test.

Clips scale proportionally to cover the entire column and are center-cropped to
exact dimensions, without stretching or padding. Square pixels, frame rate and
pixel format are shared across clips. The first source audio stream is preserved
in each timeline, normalized to AAC stereo at 48 kHz and 192 kb/s. Clips without
audio contribute silence for their duration. The final video mixes A/B/C with
equal weights using FFmpeg's normalized audio mix; no custom mixing controls yet.

Select **No Audio** in Audio Settings to omit audio tracks from clip intermediates,
A/B/C timelines, and the final assembly. Audio measurement, normalization, and mixing
are skipped in this mode.

The dockable **Audio Settings** panel sits below Render Settings. Its
**Normalize Audio → Normalization mode** selector saves one of:

- **None:** leave source levels unchanged; the final equal-weight mix remains.
- **True Peak:** measure each source's stereo audio before rendering and apply
  constant gain to target −1 dBTP. Measure and normalize the final mix separately.
  This preserves dynamics and does not equalize perceived loudness.
- **YouTube:** dynamically normalize each clip and the final mix to −14 LUFS
  integrated loudness with a −1 dBTP ceiling, using FFmpeg loudnorm. LRA is set
  to 50 LU to avoid imposing an additional narrow loudness-range target.

True Peak measurements use the same resampling, stereo conversion and duration
as rendering, and are reused when the same source appears more than once.
Missing audio and digital silence remain silent. These are pre-encoding targets;
AAC encoding can change measured peaks. Very short clips may not provide enough
audio for a meaningful integrated loudness measurement. Netflix is omitted.
Normalization settings lock during rendering and both docks appear in View.

References: [FFmpeg loudnorm](https://www.ffmpeg.org/ffmpeg-filters.html#loudnorm)
and Blackmagic Design's [Resolve 20 Colorist Guide](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-20-Colorist-Guide.pdf),
which documents the YouTube preset as −14 LKFS and −1 dBTP.

**Output Settings**, docked below Audio Settings, contains Project, Name format,
and Output folder (with Browse). Project defaults to the first source folder's
name and can be edited. The default format is `{project}.Assembly.{date}.mp4`;
`{date}` uses `YYYY-MM-DD` on the day export starts. These settings are saved.
Export uses them directly without a filename or save-location dialog. An empty
output folder stops export and displays an error in the status bar.

For example, project `Holiday` on 2026-10-23 produces
`Holiday.Assembly.2026-10-23_A.mp4`, `_B.mp4`, and `_C.mp4` sequentially,
then `Holiday.Assembly.2026-10-23_FINAL.mp4` when combining is enabled. These playable
column cuts retain their natural durations and stay beside the final output.
Uncheck **Create Final 3 Column Assembly Cut**, above the render buttons, to produce only these files.
When checked, a final pass stacks the columns, inheriting the render settings
without resizing. Shorter columns hold their last frame. This final stage is
another encode, not stream copy. There is no automatic reuse of prior outputs.

Before rendering, all planned output paths are checked together. If any exist,
an error lists the conflicting paths and no stage starts. When rendering only
A/B/C, an existing unused final file does not block the job. FFmpeg also refuses
to overwrite files created after this preflight check.
Stop rendering sends FFmpeg its normal quit command, retains completed and
partial files, and does not start later stages. Process diagnostics and exit
codes remain visible. Each column renders one source clip at a time into
temporary MOV files, then
joins them sequentially with video stream copy and one audio encode using the selected codec.
Each clip is measured (when True Peak is selected), then immediately rendered.
A is completed and saved before any processing of B begins, followed by C.
Temporary clip files are deleted as soon as their column is saved; completed
A/B/C outputs remain available if a later stage fails or is stopped.
Temporary PCM audio avoids per-clip AAC gaps. Cuts align to output frames; a
partial frame extends to the next frame boundary. The final composite opens only
A/B/C. Temporary files are removed when rendering ends or is stopped; allow disk
space for encoded clips and uncompressed stereo audio during rendering.
Source audio timestamps are preserved relative to video, including delayed
audio starts and silent gaps. Each temporary clip has matching audio/video
boundaries so timing differences do not accumulate across the column.

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
