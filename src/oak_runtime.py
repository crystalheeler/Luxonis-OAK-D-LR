"""
Runtime helpers for the portable executable.
==============================================
Four jobs that only a frozen, windowed, double-clicked program needs:

  1 Finds child executables (mediamtx, ffmpeg) inside or beside the bundle.
  2 Copies them to a fixed folder so Windows Firewall rules persist.
  3 Stops a second copy of the program from fighting over the camera.
  4 Restarts the process without a service manager.
"""

import logging
import os
import shutil
import socket
import subprocess
import sys
import time

import oak_paths

log = logging.getLogger("oak-runtime")

# Child binaries the program may start. ffmpeg is optional: without it the
# RTSP publisher stops, and the MJPEG feed, snapshots and recording continue.
CHILD_BINARIES = ("mediamtx", "ffmpeg")

# Loopback port held open for the lifetime of the process to mark it running.
# One below the RTSP port so the whole range stays together.
SINGLE_INSTANCE_PORT = 8764

# Set on a restart so the replacement process waits for the old one to exit.
RESTART_ENV = "OAK_RESTART"

_lock_socket: socket.socket | None = None


def _exe_name(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def _same_path(a: str, b: str) -> bool:
    """Compare two paths without following links. Ignores case on Windows."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def stage_binaries(names=CHILD_BINARIES) -> dict[str, str]:
    """Copy bundled child binaries into a fixed folder. Return name to path.

    A onefile bundle unpacks to a new temporary folder on every launch. A child
    started from that path gets a new Windows Firewall prompt every time,
    because the firewall keys its rules on the binary path. Copying each child
    binary to oak_paths.bin_dir() once gives it a stable path, so the user
    answers the firewall prompt one time.

    Skips the copy when the bundle does not carry the binary, and skips it when
    the destination already holds a file of the same size.
    """
    staged: dict[str, str] = {}
    target_dir = oak_paths.bin_dir()

    for name in names:
        filename = _exe_name(name)
        source   = os.path.join(oak_paths.bundle_dir(), filename)
        target   = os.path.join(target_dir, filename)

        if not os.path.isfile(source):
            # Not bundled. resolve_binary falls back to PATH.
            continue

        # Already living in the staged folder: nothing to copy.
        if _same_path(source, target):
            staged[name] = target
            continue

        try:
            if (os.path.isfile(target)
                    and os.path.getsize(target) == os.path.getsize(source)):
                staged[name] = target
                continue
            shutil.copy2(source, target)
            os.chmod(target, 0o755)
            log.info(f"Staged {filename} to {target}")
            staged[name] = target
        except OSError as e:
            log.warning(f"Could not stage {filename}: {e} — using bundle copy")
            staged[name] = source

    return staged


def resolve_binary(name: str) -> str | None:
    """Return a usable path for a child executable, or None when absent.

    Search order: the staged folder, the bundle folder, the executable folder,
    then PATH. The staged folder comes first so the firewall sees one path.
    """
    filename = _exe_name(name)
    for folder in (oak_paths.bin_dir(), oak_paths.bundle_dir(), oak_paths.app_dir()):
        candidate = os.path.join(folder, filename)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which(name)


def acquire_single_instance(timeout: float = 0.0) -> bool:
    """Reserve the loopback marker port. Return False when already running.

    Double-clicking the executable twice would otherwise start two processes.
    They would then fight over ports 8765 to 8767 and over the camera itself.

    A restart passes a timeout so the replacement process waits for the old one
    to release the port.
    """
    global _lock_socket

    deadline = time.monotonic() + timeout
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # No SO_REUSEADDR: the bind must fail while another process holds it.
        try:
            sock.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
            sock.listen(1)
            _lock_socket = sock
            return True
        except OSError:
            sock.close()
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)


def release_single_instance() -> None:
    """Close the marker port so a replacement process can take it."""
    global _lock_socket
    if _lock_socket is not None:
        try:
            _lock_socket.close()
        except OSError:
            pass
        _lock_socket = None


def restart_process(cleanup=None) -> None:
    """Replace this process with a fresh copy of itself.

    The Home Assistant add-on used to rely on the S6 supervisor to restart the
    process after SIGTERM. A portable executable has no supervisor, and Windows
    has no SIGTERM, so the process restarts itself.

    Pass a cleanup callable to stop child processes before the handover.
    """
    if cleanup is not None:
        try:
            cleanup()
        except Exception as e:
            log.error(f"Cleanup before restart failed: {e}")

    release_single_instance()
    logging.shutdown()

    env = dict(os.environ)
    env[RESTART_ENV] = "1"

    if oak_paths.is_frozen():
        argv = [sys.executable] + sys.argv[1:]
    else:
        argv = [sys.executable] + sys.argv

    if sys.platform == "win32":
        # os.execv on Windows re-quotes arguments and mangles paths that hold
        # spaces. Spawn a detached copy and exit instead.
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(argv, env=env, close_fds=True,
                         creationflags=DETACHED_PROCESS)
        os._exit(0)
    else:
        os.execve(argv[0], argv, env)


def restart_wait_seconds() -> float:
    """How long to wait for the marker port when this is a restart."""
    return 20.0 if os.environ.get(RESTART_ENV) == "1" else 0.0
