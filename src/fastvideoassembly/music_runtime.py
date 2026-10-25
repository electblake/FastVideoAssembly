"""Install the isolated CUDA runtime and download classification models."""

import json
import subprocess
import sys
from pathlib import Path

from platformdirs import user_cache_path, user_data_path

from . import APP_NAME
from .classification import GPU_MODEL_ID, MODEL_FILE, MODEL_ID


def model_cache_path():
    return user_cache_path(APP_NAME, appauthor=False) / "huggingface" / "hub"


def gpu_runtime_path():
    return user_data_path(APP_NAME, appauthor=False) / "runtimes" / "music-cu130"


def install_gpu_dependencies():
    runtime = gpu_runtime_path()
    subprocess.run([sys.executable, "-m", "uv", "venv", "--allow-existing",
                    "--python", sys.executable, str(runtime)],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    python = runtime / "Scripts" / "python.exe"
    subprocess.run([
        sys.executable, "-m", "uv", "pip", "install", "--python", str(python),
        "--torch-backend", "cu130", "torch>=2.14.1", "transformers>=5.20.2",
        "huggingface-hub>=2.3.0", "numpy>=2.5.4",
    ], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([str(python), "-c",
                    "import torch; torch.cuda.init(); print('CUDA ready:', torch.cuda.get_device_name(0))"],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def download_model(device):
    from huggingface_hub import snapshot_download

    model = GPU_MODEL_ID if device == "cuda" else MODEL_ID
    weights = "pytorch_model.bin" if device == "cuda" else MODEL_FILE
    snapshot_download(model, cache_dir=model_cache_path(),
                      allow_patterns=["*.json", "*.txt", weights])


def main():
    operation = sys.argv[1]
    if operation == "install":
        install_gpu_dependencies()
    elif operation == "download":
        download_model(sys.argv[2])
    elif operation == "classify":
        request = json.load(sys.stdin)
        subprocess.run([str(gpu_runtime_path() / "Scripts" / "python.exe"),
                        str(Path(__file__).with_name("classification.py"))],
                       input=json.dumps(request).encode(), check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    main()
