# Changelog

## [Unreleased]

## [0.8.3] - 2026-10-26

### Fixed

- Skipped videos rejected by FFprobe, removed them from project sources without deleting files, and recorded their paths and errors in Activity.
- Released failed scan workers so remaining videos finish scanning and Stop can complete, preserving progress when scanning resumes.
- Stopped adding empty Activity entries after successful video scans.

## [0.8.2] - 2026-10-25

### Added

- Added an initial-load screenshot and application logo to the README.

### Changed

- Reduced the README to features, installer instructions, and documentation links.
- Moved usage, development, and installer details into focused guides under `docs/`.

## [0.8.1] - 2026-10-25

### Added

- Added a Music Classification dock with editable Music and Talking candidates, independent thresholds, Apply buttons, mute checkboxes, and a saved worker count.
- Added classification of selected clips and timelines, with cached scores reused across scans and restarts and threshold changes applied without rescanning.
- Added CPU ONNX and NVIDIA CUDA inference, GPU precision and device controls, an isolated CUDA dependency installer, and model downloads stored in the platform cache directory.
- Added persistent per-clip mute controls in the preview and applied mute decisions during export.
- Added classification throughput and ETA, rendering frame throughput, and audio-measurement throughput and ETA.
- Added end-to-end checks for minimized, no-profile launches through the module entry point and headless launches with corrupt user settings.
- Verified that no-profile sessions never resolve the user configuration path or open settings, and that regression launches remain minimized without taking focus.

### Changed

- Displayed rendering runtime below 49% progress before switching to an estimated countdown.
- Scored music and talking together; invalidated older single-candidate scores and cached results when candidates, sources, or inference settings changed.

### Fixed

- Excluded muted clips from source normalization measurements, preserved silence during export, and included mute state in final-mix cache identities.
- Gave classification threads separate models and serialized model initialization.
- Classified only actual decoded audio samples, avoiding empty windows when an audio track ended before its video.
- Decoded audio into temporary storage and read bounded windows instead of keeping entire clips in memory.
- Bounded queued classification work so a failed result no longer left the entire scan queued behind thread-pool shutdown.
- Enabled Stop during classification, terminated its process tree, preserved completed scores and mute decisions, and replaced the stopped scan's ETA with its stopped state.

## [0.8.0] - 2026-10-24

### Added

- Added Sticky clip selections and Sticky timeline selections checkboxes below their button grids, enabled by default, with settings restored across app restarts.
- Added single-selection behavior when sticky selections are disabled, reducing existing selections to one and replacing it when another item is clicked.
- Added synchronized audio gain controls with Apply and Reset below the video preview, saved per clip for preview playback and export.
- Displayed saved source True Peak measurements and estimated levels after the applied gain; identified dynamic YouTube normalization separately.

### Fixed

- Included manual clip gains in final-mix cache identities, preserving unrelated measurements and reusing unchanged mixes across restarts.
- Skipped source normalization measurements during export when a manual gain replaces automatic normalization.
- Matched processed preview audio to export resampling, stereo conversion, and applied gain, including boosts above 0 dB.
- Canceled obsolete preview processing on clip changes and window close, and released temporary preview media after deselection.
- Preserved unapplied gain edits during selection refreshes and discarded them when changing clips.
- Kept the preview audio readout on one line to prevent selection changes from resizing the dock and shifting timeline drag coordinates.

## [0.7.5] - 2026-10-24

### Added

- Added saved render checkboxes beside division headings to include or exclude individual divisions from export.
- Included division numbers in rendering progress labels.

### Fixed

- Excluded unchecked divisions from audio measurement, rendering, output replacement checks, and timeline cleanup.
- Disabled rendering when no divisions are selected and prevented changing division selections during processing.

## [0.7.4] - 2026-10-24

### Fixed

- Made Normalize Audio reuse saved True Peak measurements and measure only new or changed clips.
- Completed fully cached normalization runs without starting FFmpeg and preserved unrelated final-mix measurements when measuring new sources.
- Confirmed individual clip measurements remain reusable after changing interim rendering, audio codec, frame rate, and video settings.

### Added

- Logged saved audio measurement reuse during normalization and rendering.
- Added regression coverage for cached-only and mixed cached/new normalization, restart reuse, changed sources, cancellation, and failures.

## [0.7.3] - 2026-10-24

### Added

- Added regression checks that shared test defaults skip settings access and window activation, while persistence tests remain minimized with temporary profiles.
- Documented no-profile, minimized launch requirements for new tests and manual smoke tests.

## [0.7.2] - 2026-10-24

### Added

- Added `-Minimize` to both launchers to start minimized without taking focus.

### Changed

- Made `-NoProfile` skip all settings and session-state reads and writes, including temporary profile files.
- Made tests use no-profile, minimized application instances by default; kept persistence tests in isolated temporary profiles.

### Fixed

- Moved direct final-mix audio inputs into filter-graph manifests so large projects no longer exceed Windows' command-line limit before FFmpeg starts.
- Rendered large direct divisions in bounded, GPU-compatible compressed segments and joined video without re-encoding; mixed and normalized audio continuously across the full division.
- Removed audio speed, batch, worker, inactivity, and runtime metrics; logged confirmed FFmpeg startup and real audio progress instead.
- Terminated active audio-measurement workers directly when Stop was clicked, including parallel analysis and final-mix measurement, instead of waiting for FFmpeg to read an interactive quit command.
- Preserved saved measurements, released processing controls, and prevented subsequent jobs from starting after audio cancellation.
- Logged Pause, Resume, and Stop actions for scanning, processing, and preview playback, with status feedback and confirmation when processing paused or stopped.
- Kept pending pause and stop requests visible during runtime and progress updates.
- Honored scanning cancellation when the last active scan finished instead of automatically creating timelines.
- Made Stop interrupt active video rendering directly as well as audio measurement.

## [0.7.1] - 2026-10-24

### Fixed

- Replaced completed-items throughput during audio measurement with average audio seconds processed per second, driven by FFmpeg timestamps.
- Showed processed audio duration, batch completion and active worker counts, and time since audio last advanced, including final-mix measurement without interim timelines.
- Added periodic per-file audio progress and completed true-peak results to the Activity log, and stopped inserting blank lines for progress-only updates.
- Updated completed audio duration immediately when a measurement finished.

## [0.7.0] - 2026-10-24

### Added

- Saved True Peak source and final-mix measurements with the project and reused them across exports and restarts.
- Added Normalize Audio to manually remeasure scanned sources without rendering video.
- Added regression coverage for restart reuse, changed files and timelines, audio settings, silent audio, and interrupted normalization.

### Changed

- Invalidated cached measurements when source file size, modification time, duration, timeline arrangement, or relevant audio rendering settings changed.
- Retained dynamic YouTube loudness processing during rendering.

### Fixed

- Preserved saved source and mix measurements when manual normalization stopped or failed before a successful replacement.
- Invalidated saved mixes after successful manual source remeasurement.

## [0.6.0] - 2026-10-24

### Added

- Added a saved Render interim timelines checkbox above timeline deletion, enabled by default to preserve existing exports.
- Added direct rendering to separate division final files when interim rendering is disabled, preserving clip normalization, frame timing, audio mixing, and True Peak source and final-mix analysis.
- Added regression coverage confirming each division's final file completes before the next division begins processing, with or without interim timelines.

### Changed

- Disabled timeline deletion when interim rendering is off and excluded unused interim paths from overwrite checks.
- Disabled Render when neither interim timelines nor final assembly output is selected.

### Fixed

- Re-enabled Check for updates after completed checks and downloads without reopening the dialog.
- Cleared stale installer readiness and download progress when checking again, and disabled checks during downloads.

## [0.5.0] - 2026-10-24

### Added

- Added Help > Check for Updates with GitHub release checks, installer download progress, cancellation, and Quit and install update.
- Delayed installer startup until the application process exits using an inherited Windows process handle.
- Added `-NoProfile` to both launchers and `Application(no_profile=True)` for isolated sessions that start with defaults and never read or modify the saved user profile.

## [0.4.0] - 2026-10-24

### Added

- Added a project skill defining functional, nonredundant UI text requirements.
- Added saved hardware decoding and scaling selectors based on Windows GPU vendors and FFmpeg capabilities, with CPU/CUDA interpolation and Quick Sync scaling modes.
- Exposed all seven NVENC presets, labeled Fastest through Slowest, with corresponding CPU H.264 presets.
- Added Apply and Reset beside CPU filter threads, keeping edits pending until explicitly applied.
- Added independent multi-selection for clips and timelines, selection counts in their control groups, and timeline-local organizing and shuffling.
- Added contiguous multi-clip moves by dragging or using Forward, Backward, Start, and End.
- Added Replace files and continue to output-conflict dialogs, allowing replacement of the listed outputs while keeping Cancel as the default.
- Added a Columns selector with 3 and 4 options before Divisions, including matching display rows, balanced timelines, final video widths, audio mixes, cleanup, and active-state restoration.
- Added Copy output and Clear output beneath the Activity log, plus an unchecked Keep logs between runs option above the timeline actions.
- Added saved CPU filter threads and bounded parallel True Peak analysis workers, defaulting to four threads and two workers.
- Added active source metadata, timeline membership, and manual clip ordering persistence in the platformdirs INI settings file, with automatic saving before window close and File > Exit.
- Added ETA and rendering frames/s to render progress, and completed items/s to audio analysis and source scanning progress; showed runtime in the status bar during rendering and audio analysis.
- Added Open folder beneath the output folder controls to open the selected location in the system file manager.
- Added an opt-in Delete timelines after final render setting that deletes only a division's rendered timeline files after its final cut finishes successfully.
- Added Divisions to balance lettered timelines across all sources, display divisions side by side, and render a separate final cut per division.

### Changed

- Renamed the assembler tab to Column Assembly and removed fixed per-column dimensions from output-size labels.
- Renamed Process log to Activity and cleared its output when creating timelines or starting a render unless Keep logs between runs is checked.
- Deferred new-source metadata scanning until Create Timelines; restored cached metadata and timeline arrangements without rescanning or rebalancing.
- Rendered each timeline directly from original clips in one FFmpeg filter graph, removing temporary per-clip renders and their concat pass.
- Replaced JSON render-setting storage with typed INI keys; reset the former JSON-only render options once.
- Flattened Normalize Audio into the audio settings form and shortened UI labels using ASCII punctuation.
- Removed duplicate scan counts, render percentages, and measurement log messages.
- Moved Create final assembly above the render buttons; disabling it exports only the individual timelines.
- Removed the redundant Output Length label below the timeline controls.
- Labeled timelines alphabetically and replaced middle-dot separators throughout the application with dashes.

### Removed

- Removed duplicate timeline clip lists; source selection and timeline clicks now drive preview, movement, and removal directly.

### Fixed

- Included the timeline style module in the Windows installer so the installed application can import it.
- Preserved saved hardware selections as unavailable when a GPU or FFmpeg capability disappears, preventing blank selectors from overwriting those settings.
- Made GPU inventory command failures terminate detection instead of silently reporting missing capabilities.
- Removed redundant hardware-control tooltip text.
- Calculated drag placement after closing source gaps, with an insertion marker at the actual final block start instead of the old pre-removal boundary.
- Kept all-timeline organizing within existing tracks instead of redistributing manually arranged clips.
- Corrected Forward and Backward movement at timeline ends and clipped number labels to their own segments.
- Corrected remaining three-column assumptions in the unreleased documentation for configurable layouts.
- Identified the failed source correctly when a parallel audio measurement batch ended out of order.
- Preserved completed columns and stopped paused exports without consuming stale FFmpeg progress.
- Stopped the runtime timer when pausing or ending an export and tied its lifetime to the main window.
- Preserved timeline zoom and source-list state when toggling final assembly, avoiding an unnecessary rebuild of the editor.

## [0.3.2] - 2026-10-23

### Added

- Added Clear All Sources below Remove Selected Clips to empty the source list, timelines, preview, and saved source state.
- Added No Audio to Audio Settings, omitting audio streams from clip intermediates, A/B/C timelines, and the final assembly while skipping normalization and audio measurement.

### Fixed

- Cleared stale progress, ETA, and status messages when clearing all sources.

## [0.3.1] - 2026-10-23

### Changed

- Installed Start Menu and desktop shortcuts automatically, including during upgrades and silent installs.

## [0.3.0] - 2026-10-23

### Added

- Saved source video paths with window state and restored them on startup, preserving source order and custom project names without creating timelines.

### Changed

- Stopped automatic timeline creation and sorting after imports; added Create Timelines beside Render Column Assembly and enlarged the Stop button.
- Grouped render progress by A, B, C, and FINAL, with a duration-weighted completion percentage and estimated remaining time in `HH:MM:SS`; scanning uses completed/total video counts.

### Fixed

- Persisted source additions, removals, and clearing immediately, including the full import queue so interrupted scans retain pending sources.
- Formatted column lengths, clip times, output length, and preview times as `HH:MM:SS`, including durations over one hour.

## [0.2.0] - 2026-10-23

### Added

- Added mixed video/folder selection through Add Videos and direct drops onto the source list for incremental imports.
- Added a source-list remove button and Shift/Ctrl multi-selection for removing sources and their timeline segments together.
- Added a dockable video preview with paused first frame, playback controls, and scrubbing.
- Linked clip selection across the source library, central lists, timeline, and preview.
- Added Remove Selected Clip without deleting source files or rearranging remaining clips.
- Added persistent Output Settings for project name, filename template, and output folder.

### Changed

- Moved the three-column editor into a dedicated `3 Column Assembly` tab, with portrait filtering local to that assembler.
- Moved shared progress above the process log and removed assembler-specific source-library text.
- Completed each column end to end before starting the next, measuring audio immediately before each clip render and deleting temporary files after saving the column.
- Generated `_A`, `_B`, `_C`, and `_FINAL` filenames automatically, without save dialogs.
- Reset progress for each processing step; displayed busy progress during metadata scans.
- Replaced duration-rank mixing with explicit Shortest First and Longest First sorting.

### Fixed

- Preserved manual timeline ordering and progress when imports contained no new videos.
- Restricted source drops to local files and folders, preventing web URLs from importing the working directory.
- Used copy semantics for source drops so importing never requests a file move.
- Released Add Videos dialogs after accepting or cancelling them.
- Replaced source multi-selection with the clicked clip even when its timeline segment or column row was already current, preventing unintended batch removal.
- Cleared stale preview and clip controls after source deselection, and disabled single-clip movement for multiple selected sources.
- Updated the central remove button label to reflect batch removal.
- Kept rendering progress below 100% until FFmpeg exits successfully, and identified user cancellation as stopped.
- Aligned timeline blocks, clip boundaries, click selection, and Output Length with frame-rounded render durations.
- Prevented clicks in gaps between timeline rows from selecting nearby clips.
- Preserved completed columns when a later step failed or was stopped.

### Removed

- Removed the ineffective Balanced ordering option.
- Removed introductory and duplicate settings text from the central editor.

## [0.1.0] - 2026-10-23

### Added

- Independent Qt application and Windows installer based on FastVideoCropper.
- Portrait folder import, three balanced timelines, manual ordering and moves.
- Silent three-column H.264 render with duration progress and process diagnostics.
