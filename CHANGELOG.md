# Changelog

## [Unreleased]

### Added

- Added Open Output Folder beneath the output folder controls to open the selected location in the system file manager.
- Added an opt-in Remove timelines after FINAL setting that deletes only a division's three rendered timeline files after its final cut finishes successfully.
- Added Divisions to balance 3 × N lettered timelines across all sources, display each triple side by side on three rows, and render a separate final cut per division.

### Changed

- Deferred metadata scanning until Create Timelines; adding, dropping, and restoring sources now loads filenames only and remains available for repeated drops.
- Moved Create Final 3 Column Assembly Cut above the render buttons; disabling it exports only A/B/C timelines.
- Removed the redundant Output Length label below the timeline controls.
- Labeled columns A, B, and C and replaced middle-dot separators throughout the application with dashes.

### Removed

- Removed the three duplicate timeline clip lists; source selection and timeline clicks now drive preview, movement, and removal directly.

### Fixed

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
