# Changelog

## [Unreleased]

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
