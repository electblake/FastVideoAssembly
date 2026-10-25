# User guide

## Import and arrange

- Use **Add Videos**, Ctrl+O, or drag files and folders onto the window. Supported formats are MP4, MKV, MOV, AVI, and WebM; folder imports include immediate files only.
- **Create Timelines** scans sources and balances portrait clips across columns by duration. Square and landscape clips stay in the source library.
- Choose three or four **Columns** and a **Divisions** count. Changing either clears the arrangement; use **Create Timelines** to rebuild it.
- Each division has its own timelines and output. Uncheck a division to exclude it from rendering.
- Select clips in the source list or timeline to preview them. Sticky selection allows multiple selections; **Select None** clears the corresponding selection.
- Drag selected clips within their timeline, or use **Move Forward**, **Move Backward**, **Move to Start**, and **Move to End**.
- Click unused timeline space to select a timeline. **Shortest First**, **Longest First**, and **Shuffle** affect selected timelines, or all timelines when none are selected.
- **Remove selected** removes sources and their timeline entries without deleting source files.

## Video

- **Render Settings** controls output size, frame rate, encoder, speed, quality, decoding, and scaling.
- Defaults are 1920 × 1080 at 30 fps, NVIDIA HEVC Main 10, Balanced/P4, and CQ 20. NVIDIA H.264 and CPU H.264 are also available.
- Lower quality values produce higher-quality, larger files. NVIDIA CQ and CPU CRF use different scales.
- Decoding and scaling default to CPU. Available hardware options depend on the GPU and FFmpeg build; select a compatible backend explicitly.
- Clips scale proportionally and crop centrally to fill each column. Shorter timelines hold their last frame in the final assembly.
- **CPU filter threads** changes take effect after **Apply**; **Reset** restores the last applied value.

## Audio

- **Audio Settings** offers **None**, **True Peak**, and **YouTube** normalization, or **No Audio** to omit audio entirely.
- **None** preserves clip levels. The final assembly mixes timelines with equal weights.
- **True Peak** applies constant gain toward −1 dBTP to each clip and measures the final mix separately. Cached measurements are reused while the relevant sources and settings match.
- **YouTube** dynamically normalizes clips and the final mix to −14 LUFS integrated loudness with a −1 dBTP ceiling.
- **Normalize Audio** measures scanned sources that need True Peak measurements. **Audio analysis workers** controls concurrency.
- **Audio gain** in Preview overrides a clip’s automatic normalization after **Apply**. **Reset** discards unapplied edits; switching clips also discards them.
- **Mute** silences a clip in preview and export. Clips without audio contribute silence.
- Output audio uses AAC stereo at 48 kHz and 192 kb/s. AAC encoding may change measured peaks.
- **Music Classification** scores music and talking with editable candidates and thresholds. Classify selected clips or timelines, then apply mute decisions. CPU inference uses ONNX; CUDA inference requires its separate dependencies and model downloads.

## Export

- Set **Project**, **Name format**, and **Output folder** in Output Settings. The default name is `{project}.Assembly.{date}.mp4`, with the export date formatted as `YYYY-MM-DD`.
- **Render interim timelines** saves individual timeline files with letter suffixes such as `_A.mp4`.
- **Create final assembly** produces a combined file ending in `_FINAL.mp4`. Multiple divisions use timeline-letter suffixes such as `_FINAL_ABC.mp4` and `_FINAL_DEF.mp4`.
- Disable **Render interim timelines** to export each division directly to its final file. Keep **Create final assembly** enabled for this mode.
- **Delete timelines after final render** removes a division’s intermediate files only after its final succeeds. Source videos are never deleted.
- Existing output files appear in a replacement dialog before rendering. Cancel keeps them unchanged; **Replace files and continue** authorizes replacement of the listed outputs.
- Stop retains completed and partial outputs and prevents later stages from starting.
- Activity shows progress, ETA, throughput, and logs. **Keep logs between runs** preserves earlier output; **Copy output** copies the log.

## Settings and updates

- The source library, scanned metadata, arrangement, clip gains, and preferences persist in the application’s user configuration directory. Remove and re-add a changed source to rescan its video metadata.
- **Settings → Appearance** changes the theme and icon. **View** reopens docks.
- **Help → Install in File Explorer** adds per-user context-menu entries.
- **Help → Check for Updates** downloads the latest stable installer. **Quit and install update** closes the app before starting Setup.
