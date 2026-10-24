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
One active source list and its scanned metadata are saved in `settings.ini` under
`platformdirs.user_config_path(APP_NAME, appauthor=False)`. QSettings stores native
INI values and arrays, with no JSON storage or project files. Each completed scan
immediately saves duration, display dimensions, and audio presence. Restarting
restores both scanned clips and unscanned sources in their original order, plus
timeline membership and manual clip ordering. Timeline edits, sorting, and division
changes save immediately to the same active state. Startup restores the arrangement
without rebalancing or scanning. Create Timelines explicitly rebuilds it, scanning
only remaining sources. Removing or clearing sources also removes their saved
metadata and timeline entries. To rescan a changed source file, remove it and add it again.
Render options use typed INI keys; the former JSON render-settings entry is removed
and its values reset to defaults once. Window state is saved on close.
Sorting is enabled once all sources are scanned.

The shared source library lists filenames without assembler-specific labels or
filtering. The **3 Column Assembly** central tab accepts display aspect ratios
below 1; square and landscape clips remain available in the shared source library.
Rotation metadata and sample aspect ratio are considered. Longest clips are allocated to the currently
shortest column, then each column is sorted shortest to longest. This is a
duration-balancing heuristic, not a promise of an optimal equal partition.

All three-column editing and render controls live in that tab. Preview, render,
audio, and output settings remain shared docks. Progress appears directly above
the log inside the shared Activity dock, which opens when processing starts.
Copy output selects and copies the complete log; Clear output empties it.
Creating timelines or starting a render clears the log unless Keep logs between
runs is checked. This checkbox starts unchecked and sits above the action buttons.
Render progress shows runtime and rendering throughput in frames/s; audio analysis
and source scanning show completed items/s. ETA appears only in the status bar.
Runtime and throughput exclude paused time.

The central timeline uses a shared seconds axis and duration-scaled blocks,
including the same output-frame rounding used by rendering.
Click a block or list entry to select it. Move earlier/later changes playback
order; move previous/next transfers the clip to the end of an adjacent timeline,
including across division boundaries.
**Shortest First** sorts clips by ascending duration; **Longest First** sorts
by descending duration. Both buttons first redistribute all eligible source clips
to keep all timeline totals similar; ordering does not change those totals.
The former Balanced ordering has been removed because alternating duration ranks
did not distribute clip lengths evenly over playback time.
Selecting a source or timeline segment shares one selection across both views.
The dockable **Preview** above Render Settings
shows the selected source with Play/Pause, Stop, and a scrubber.
**Remove selected** removes the source and its timeline entries from the
assembly without deleting the file or reordering other clips. Use either sorting
button when you want to redistribute the remaining clips.
Every timeline must contain a clip before rendering is enabled.

**Divisions** beside the final-cut checkbox defaults to 1. Set it to 2 for six
balanced timelines (A–F), 3 for nine (A–I), and so on. Changing this setting clears
the arrangement; Create Timelines or a sort button rebuilds it explicitly.
Each group of three appears after the previous group on the same three plot rows,
separated by a vertical line. Timelines retain their own letter and duration.
The source list is the only clip list.

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
**Normalize Audio** selector saves one of:

- **None:** leave source levels unchanged; the final equal-weight mix remains.
- **True Peak:** measure each source's stereo audio before rendering and apply
  constant gain to target −1 dBTP. Measure and normalize the final mix separately.
  This preserves dynamics and does not equalize perceived loudness.
- **YouTube:** dynamically normalize each clip and the final mix to −14 LUFS
  integrated loudness with a −1 dBTP ceiling, using FFmpeg loudnorm. LRA is set
  to 50 LU to avoid imposing an additional narrow loudness-range target.

True Peak measurements use the same resampling, stereo conversion and duration
as rendering, and are reused when the same source appears more than once.
**Audio analysis workers** sets the maximum concurrent True Peak measurements
before each column render (default 2). Measurements run in bounded batches;
pause takes effect after the active batch, and stop signals all active workers.
The final mix is measured after its columns finish.
**CPU filter threads** in Render Settings controls column and final render filter
graphs (default 4). Both settings are saved. Input decoders remain limited to one
thread each because a column opens multiple sources. GPU processing is unchanged.
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
Uncheck **Create final assembly**, above the render buttons, to produce only these files.
With multiple divisions, timelines continue as `_D`, `_E`, `_F`, etc. Each triple
has its own combined output: `_FINAL_ABC`, `_FINAL_DEF`, and so on. A single
division retains `_FINAL`. Each triple and its optional final finish before the
next triple starts; all target filenames are checked before rendering begins.
**Delete timelines after final render** is off by default. When enabled, each completed
final deletes only its own three rendered timeline files. Failed or stopped finals
retain their timeline files. Source videos are never deleted. The option is disabled
when final creation is unchecked.
When checked, a final pass stacks the columns, inheriting the render settings
without resizing. Shorter columns hold their last frame. This final stage is
another encode, not stream copy. There is no automatic reuse of prior outputs.

Before rendering, all planned output paths are checked together. If any exist,
an error lists the conflicting paths and no stage starts. When rendering only
A/B/C, an existing unused final file does not block the job. FFmpeg also refuses
to overwrite files created after this preflight check.
Stop rendering sends FFmpeg its normal quit command, retains completed and
partial files, and does not start later stages. Process diagnostics and exit
codes remain visible. Each timeline is encoded in one FFmpeg process directly
from its original source clips, with no per-clip temporary video or audio files.
The filter graph crops, scales, aligns frame boundaries, normalizes audio,
and concatenates the clips before encoding the timeline output once.
When True Peak is selected, source audio is measured before that timeline's render.
A is completed and saved before B starts, followed by C. Completed timeline
outputs remain available if a later stage fails or is stopped. The final composite
reads those timeline outputs. Only small filter-graph text files are temporary;
these are deleted after their timeline completes or when rendering ends or stops.
Source audio timestamps are preserved relative to video, including delayed
audio starts and silent gaps. Each clip has matching audio/video boundaries
so timing differences do not accumulate across the timeline.

Settings → Appearance offers the same qt-themes palettes and icon variants as
FastVideoCropper. QSettings stores preferences, Divisions, geometry, and dock positions
in platformdirs' FastVideoAssembly `settings.ini`. Clip ordering
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
