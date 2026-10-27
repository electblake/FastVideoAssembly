"""Run python-ffmpeg commands off the Qt UI thread."""

import asyncio
from threading import Thread

from ffmpeg.asyncio import FFmpeg
from PySide6.QtCore import QObject, Signal


class MediaCommand(FFmpeg):
    """Execute the argument lists produced by the assembly filter builders."""

    def __init__(self, executable, arguments):
        super().__init__(executable)
        self.command_arguments = [executable, *arguments]

    @property
    def arguments(self):
        return self.command_arguments


class MediaTask(QObject):
    progress = Signal(object)
    stderr = Signal(str)
    finished = Signal()
    loop = asyncio.new_event_loop()
    thread = Thread(target=loop.run_forever, name="media-tasks", daemon=True)
    thread.start()

    def __init__(self, command, parent):
        super().__init__(parent)
        self.command = command
        self.stop_requested = False
        self.active = False
        self.terminated = False
        self.lines = []
        command.on("progress", self.progress.emit)
        command.on("stderr", self.read_line)

    def read_line(self, line):
        self.active = True
        self.lines.append(line)
        self.stderr.emit(line)
        if self.stop_requested:
            self.request_stop()

    async def execute(self):
        self.execution = asyncio.current_task()
        return await self.command.execute()

    def start(self):
        self.future = asyncio.run_coroutine_threadsafe(self.execute(), self.loop)
        self.future.add_done_callback(lambda future: self.finished.emit())

    def stop(self):
        self.loop.call_soon_threadsafe(self.request_stop)

    def request_stop(self):
        self.stop_requested = True
        if self.active and not self.terminated and not self.execution.done():
            self.terminated = True
            self.command.terminate()
