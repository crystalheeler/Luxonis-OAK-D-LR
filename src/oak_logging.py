"""
File logging for the OAK camera bridge.
=========================================
A windowed executable has no console, so every message must reach a file.
This module does three jobs:

  1 Writes rotating log files next to the executable.
  2 Replaces sys.stdout and sys.stderr when PyInstaller sets them to None.
  3 Drains a child process pipe into the log, for mediamtx and ffmpeg.

Call setup_logging() once, before any other import writes a log record.
"""

import logging
import logging.handlers
import os
import sys
import threading

import oak_paths

LOG_NAME        = "oak_camera.log"
MAX_BYTES       = 2 * 1024 * 1024   # 2 MB per file
BACKUP_COUNT    = 5                 # 10 MB total
LOG_FORMAT      = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT     = "%Y-%m-%d %H:%M:%S"

_log_path: str | None = None


class _StreamToLog:
    """File-like object that forwards writes to a logger.

    PyInstaller sets sys.stdout and sys.stderr to None in windowed builds. A
    bare print() then raises AttributeError on None.write. Installing this
    object keeps third party code that prints from crashing the process.
    """

    def __init__(self, logger: logging.Logger, level: int):
        self._logger = logger
        self._level  = level
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line.rstrip())
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._logger.log(self._level, self._buffer.rstrip())
        self._buffer = ""

    def isatty(self) -> bool:
        return False

    # Some libraries probe for these. Return harmless values.
    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def fileno(self) -> int:
        raise OSError("redirected stream has no file descriptor")


def log_path() -> str | None:
    """Full path of the active log file, or None before setup_logging runs."""
    return _log_path


def setup_logging(level: int = logging.INFO, capture_streams: bool = True) -> str:
    """Attach a rotating file handler to the root logger. Return the log path.

    Adds a console handler as well when a console exists. Set capture_streams
    to False in the Home Assistant add-on, where the Supervisor already reads
    stdout and shows it in the add-on log.
    """
    global _log_path

    _log_path = os.path.join(oak_paths.log_dir(), LOG_NAME)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)

    # Drop handlers from an earlier call or from logging.basicConfig.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        _log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # A console exists in the add-on, in a source run, and in a console build.
    if sys.stderr is not None and sys.stderr.fileno:
        try:
            sys.stderr.fileno()
            console = logging.StreamHandler(sys.stderr)
            console.setFormatter(formatter)
            root.addHandler(console)
        except (OSError, ValueError, AttributeError):
            pass    # windowed build: the file handler is the only sink

    if capture_streams:
        if sys.stdout is None or not hasattr(sys.stdout, "write"):
            sys.stdout = _StreamToLog(logging.getLogger("stdout"), logging.INFO)
        if sys.stderr is None or not hasattr(sys.stderr, "write"):
            sys.stderr = _StreamToLog(logging.getLogger("stderr"), logging.ERROR)

    logging.getLogger("oak-logging").info(f"Logging to {_log_path}")
    return _log_path


def drain_pipe(stream, logger_name: str, level: int = logging.INFO) -> threading.Thread:
    """Read a child process pipe line by line into the log.

    mediamtx writes to stdout and ffmpeg writes to stderr. Both vanish without
    a console. This thread copies each line into the log file instead.
    """
    logger = logging.getLogger(logger_name)

    def _pump():
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    logger.log(level, line)
        except (ValueError, OSError):
            pass        # pipe closed when the child exited
        finally:
            try:
                stream.close()
            except OSError:
                pass

    thread = threading.Thread(target=_pump, name=f"log-{logger_name}", daemon=True)
    thread.start()
    return thread
