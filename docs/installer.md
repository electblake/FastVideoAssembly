# Windows installer

- Requires Inno Setup 6.7.3 and the locked project environment: `uv sync --locked`.
- Build with `uv run python packaging/build.py --iscc "C:\Users\shoji\AppData\Local\Programs\Inno Setup 6\ISCC.exe"`.
- Outputs `dist/installer/FastVideoAssembly-<version>-windows-amd64-Setup.exe` and its SHA-256 file.
- Setup downloads hash-verified private Python, uv, and FFmpeg versions pinned in `packaging/python.json`, `packaging/uv.json`, and `packaging/vendor.json`.
- Installation requires internet access and creates per-user Start Menu and desktop shortcuts without changing PATH or system Python.
- The application uses the independent `electblake.FastVideoAssembly` identity for installation and Explorer integration.
- Source licenses and third-party notices ship with the installer. Builds are unsigned.
- This project has no VM infrastructure or VM testing workflow. VM testing is not available and is not part of the release process. Do not introduce it as an optional check, prerequisite, pending task, or release limitation. Generic packaging-skill VM requirements do not apply.

## Release

Use the `gh-cli` skill and GitHub CLI (`gh`) for release operations. A user request to publish a release authorizes publication after the required checks; do not stop at a draft or ask again.

1. Run `uv run pytest` and `uv run ruff check .`, and resolve failures before releasing.
2. Update `CHANGELOG.md`, bump the requested version in `pyproject.toml` and `uv.lock`, and run `uv sync --locked`.
3. Build the installer using the command above. Verify its version and compare its SHA-256 with the generated `.exe.sha256` file.
4. Commit the release changes and push the release commit to GitHub.
5. Write release notes to a file and publish the installer and checksum with `gh release create`. Use the full commit SHA for `--target` and `--notes-file` for multiline notes:

   ```powershell
   $releaseVersion = '0.8.3' # Replace with the version being released.
   $releaseCommit = git rev-parse HEAD
   gh release create "v$releaseVersion" "dist/installer/FastVideoAssembly-$releaseVersion-windows-amd64-Setup.exe" "dist/installer/FastVideoAssembly-$releaseVersion-windows-amd64-Setup.exe.sha256" --target $releaseCommit --title "FastVideoAssembly $releaseVersion" --notes-file "build/release-$releaseVersion.md" --latest
   ```

6. If the release already exists as a prepared draft, publish it with `gh release edit "v$releaseVersion" --draft=false --latest` instead of creating another release.
7. Verify publication and uploaded assets with `gh release view "v$releaseVersion" --json isDraft,url,assets`, then report the release URL and checks actually performed.
