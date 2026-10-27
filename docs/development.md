# Development

## Run

- Install Python 3.12+, uv, and FFmpeg/FFprobe 8+ on PATH.
- Install locked dependencies with `uv sync --locked`.
- Launch with `uv run fastvideoassembly`; optional trailing arguments accept video and folder paths.
- Use `uv run fastvideoassembly -NoProfile` for default settings without reading or writing profile or session state.
- Add `-Minimize` for a background smoke test: `uv run fastvideoassembly -NoProfile -Minimize`.
- Programmatic callers can use `Application(no_profile=True, minimize=True)`.

## Checks

- Run `uv run pytest` and `uv run ruff check .`.
- Keep regression coverage in three domain suites: `tests/test_app.py` (editing, preview, persistence, export), `tests/test_media.py` (assembly, timeline ordering, rendered frames, audio), and `tests/test_services.py` (classification workers, runtime setup, hardware selection, updates).
- Test related actions as one workflow using the same application instance. Create another instance only to verify restart behavior; keep separate workflows independent.
- Reuse the session-scoped `preview_source` fixture as read-only media. Write derived media and outputs under each test's `tmp_path`.
- Cover representative render paths at small resolutions. Avoid restoring exhaustive codec/layout/normalization matrices or per-control window launches.
- Application test fixtures default to no-profile, minimized windows. Preserve these defaults in new tests.
- Mark persistence tests with `@pytest.mark.profile`; their settings use an isolated temporary directory.
- Pass `-NoProfile -Minimize` to application subprocesses in tests. These flags belong to the app, not pytest or FFmpeg.

## Rendering

- Portrait eligibility uses display aspect ratio, including rotation and sample aspect ratio.
- Balancing assigns the longest remaining clip to the shortest timeline, then sorts each timeline shortest to longest.
- Timeline blocks and exports use the same output-frame rounding.
- Interim mode encodes each timeline from its sources in one FFmpeg process, then encodes the final stacked composition from those files.
- Direct final mode bounds decoder count and command size with temporary compressed video segments, joined without another video encode. Audio is mixed continuously during the join.
- Audio timestamps retain their relationship to video, including delayed starts and silent gaps.
- Crop, frame-rate conversion, padding, concatenation, and stacking use CPU filters. Hardware decoding or scaling does not guarantee faster rendering.
- Temporary filter graphs and direct-render segments are removed when processing completes or is canceled.
- Settings use QSettings under `platformdirs.user_config_path(APP_NAME, appauthor=False)`.

## Packaging

- See [Windows installer](installer.md).
