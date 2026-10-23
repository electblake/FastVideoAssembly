# Changelog

## [Unreleased]

### Added

- Added a dockable video preview with paused first frame, playback controls, and scrubbing.
- Linked clip selection across the source library, central lists, timeline, and preview.
- Added Remove Selected Clip without deleting source files or rearranging remaining clips.
- Added persistent Output Settings for project name, filename template, and output folder.

### Changed

- Completed each column end to end before starting the next, measuring audio immediately before each clip render and deleting temporary files after saving the column.
- Generated `_A`, `_B`, `_C`, and `_FINAL` filenames automatically, without save dialogs.
- Reset progress for each processing step; displayed busy progress during metadata scans.
- Replaced duration-rank mixing with explicit Shortest First and Longest First sorting.

### Fixed

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
