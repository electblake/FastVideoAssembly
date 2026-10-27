"""Compile the small online installer from pinned download manifests."""

import argparse
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--iscc", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
(root / "build").mkdir(exist_ok=True)
packages = {package["name"]: package for package in tomllib.loads((root / "uv.lock").read_text())["package"]}
(root / "build/gpu-media-requirements.txt").write_text(
    "--require-hashes\n" + "\n".join(
        f"{name}=={packages[name]['version']} --hash={packages[name]['wheels'][0]['hash']}"
        for name in ("python-ffmpeg", "pyee", "typing-extensions")
    ) + "\n"
)
definitions = []
for name, filename in (
    ("Uv", "uv.json"),
    ("FFmpeg", "vendor.json"),
    ("Python", "python.json"),
):
    manifest = json.loads((root / "packaging" / filename).read_text())
    for field, suffix in (
        ("url", "Url"),
        ("sha256", "Hash"),
        ("download_size", "DownloadSize"),
        ("extracted_size", "Size"),
    ):
        definitions.append(f'#define {name}{suffix} "{manifest[field]}"')
    if name == "Python":
        definitions.append(f'#define PythonTarHash "{manifest["tar_sha256"]}"')
        definitions.append(f'#define PythonTarSize "{manifest["tar_size"]}"')
(root / "build/downloads.iss").write_text("\n".join(definitions) + "\n")
subprocess.run(
    [
        str(args.iscc),
        f"/DMyAppVersion={version}",
        str(root / "packaging/installer.iss"),
    ],
    cwd=root,
    check=True,
)
installer = root / f"dist/installer/FastVideoAssembly-{version}-windows-amd64-Setup.exe"
with installer.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
installer.with_suffix(".exe.sha256").write_text(f"{digest}  {installer.name}\n")
print(installer)
