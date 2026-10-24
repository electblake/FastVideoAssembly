# Windows online installer

Uses FastVideoCropper's pinned uv, Python and FFmpeg downloads and private runtime
layout, with independent `electblake.FastVideoAssembly` identity, shortcuts,
Explorer keys, cache and installation directory. Source and dependencies are
installed independently; FastVideoCropper is not required or modified.

```powershell
uv sync --locked
uv run python packaging/build.py --iscc "C:\Users\shoji\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
```

Requires Inno Setup 6.7.3. Output is
`dist/installer/FastVideoAssembly-0.7.2-windows-amd64-Setup.exe` plus SHA-256.
Setup downloads hash-verified private Python 3.13.12, uv and FFmpeg 8.1.2;
Internet is required for installation. Application use is offline afterward.
No PATH or system Python changes. Source licenses and third-party notices are
included. Setup creates Start Menu and desktop shortcuts for the current user.
This build is unsigned. Clean-machine installation, upgrade and
uninstallation must be verified before release.
