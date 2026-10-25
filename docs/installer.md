# Windows installer

- Requires Inno Setup 6.7.3 and the locked project environment: `uv sync --locked`.
- Build with `uv run python packaging/build.py --iscc "C:\Users\shoji\AppData\Local\Programs\Inno Setup 6\ISCC.exe"`.
- Outputs `dist/installer/FastVideoAssembly-<version>-windows-amd64-Setup.exe` and its SHA-256 file.
- Setup downloads hash-verified private Python, uv, and FFmpeg versions pinned in `packaging/python.json`, `packaging/uv.json`, and `packaging/vendor.json`.
- Installation requires internet access and creates per-user Start Menu and desktop shortcuts without changing PATH or system Python.
- The application uses the independent `electblake.FastVideoAssembly` identity for installation and Explorer integration.
- Source licenses and third-party notices ship with the installer. Builds are unsigned.
- Verify installation, launch, upgrade, silent installation, and uninstallation in a disposable Windows environment before release.
