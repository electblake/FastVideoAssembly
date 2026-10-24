"""GitHub release updates and the Windows installer handoff."""

import base64
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import requests
from platformdirs import user_cache_path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from . import APP_NAME, APP_VERSION

RELEASE_URL = "https://api.github.com/repos/electblake/FastVideoAssembly/releases/latest"


def latest_release():
    response = requests.get(RELEASE_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def download_installer(asset, directory, cancelled, progress):
    destination = directory / asset["name"]
    partial = destination.with_suffix(".part")
    with requests.get(asset["browser_download_url"], stream=True, timeout=30) as response:
        response.raise_for_status()
        received = 0
        with partial.open("wb") as output:
            for block in response.iter_content(64 * 1024):
                if cancelled.is_set():
                    break
                output.write(block)
                received += len(block)
                progress(received, asset["size"])
    if cancelled.is_set():
        partial.unlink()
        return None
    partial.replace(destination)
    return destination


def install_after_exit(installer):
    import _winapi

    # Inherit an already-open process handle: even an early parent exit cannot
    # race with PID lookup, and the helper does not use the installed runtime.
    handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, True, os.getpid())
    installer_literal = str(installer).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class UpdateWait {{
    [DllImport("kernel32.dll")]
    public static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
}}
'@
[UpdateWait]::WaitForSingleObject([IntPtr]{handle}, [uint32]::MaxValue) | Out-Null
Start-Process -FilePath '{installer_literal}'
"""
    startup = subprocess.STARTUPINFO(lpAttributeList={"handle_list": [handle]})
    helper = subprocess.Popen(
        [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         "-NoProfile", "-NonInteractive", "-EncodedCommand",
         base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
        startupinfo=startup,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        cwd=installer.parent,
    )
    _winapi.CloseHandle(handle)
    return helper


class UpdateDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.window)
        self.controller = controller
        self.setWindowTitle("Check for Updates")
        self.setModal(True)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.cancelled = Event()
        self.installer = None
        layout = QVBoxLayout(self)
        details = QFormLayout()
        details.addRow("Application", QLabel(APP_NAME))
        details.addRow("Current version", QLabel(APP_VERSION))
        layout.addLayout(details)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.check_button = QPushButton("Check for updates")
        self.download_button = QPushButton("Download")
        self.download_button.setEnabled(False)
        actions = QHBoxLayout()
        actions.addWidget(self.check_button)
        actions.addWidget(self.download_button)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.install_button = QPushButton("Quit and install update")
        self.install_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.install_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.check_button.clicked.connect(self.check)
        self.download_button.clicked.connect(self.download)
        self.install_button.clicked.connect(self.install)
        self.cancel_button.clicked.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.completed)
        self.finished.connect(self.stop)

    def check(self):
        self.check_button.setEnabled(False)
        self.status.setText("Checking...")
        self.operation = "check"
        self.future = self.executor.submit(latest_release)
        self.timer.start()

    def completed(self):
        if self.operation == "download":
            self.set_progress(*self.transfer_progress)
        if not self.future.done():
            return
        self.timer.stop()
        result = self.future.result()
        if self.operation == "check":
            version = result["tag_name"].removeprefix("v")
            if tuple(map(int, version.split("."))) > tuple(map(int, APP_VERSION.split("."))):
                name = f"FastVideoAssembly-{version}-windows-amd64-Setup.exe"
                self.asset = next(asset for asset in result["assets"] if asset["name"] == name)
                self.status.setText(f"Version {version} available")
                self.download_button.setEnabled(True)
            else:
                self.status.setText("Up to date")
        else:
            self.installer = result
            self.progress.setValue(100)
            self.status.setText("Download complete")
            self.install_button.setEnabled(True)

    def download(self):
        self.download_button.setEnabled(False)
        self.status.setText("Downloading...")
        cache = user_cache_path(APP_NAME, appauthor=False) / "updates"
        cache.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(dir=cache))
        self.operation = "download"
        self.transfer_progress = (0, self.asset["size"])
        self.future = self.executor.submit(
            download_installer, self.asset, directory, self.cancelled, self.report_progress,
        )
        self.timer.start()

    def report_progress(self, received, total):
        self.transfer_progress = (received, total)

    def set_progress(self, received, total):
        self.progress.setValue(min(99, received * 100 // total))

    def install(self):
        if self.controller.window.close():
            self.controller.update_helper = install_after_exit(self.installer)
            self.accept()
            QApplication.instance().quit()

    def stop(self):
        self.timer.stop()
        self.cancelled.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
