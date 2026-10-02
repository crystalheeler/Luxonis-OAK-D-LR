"""
Platform path resolution for the OAK camera bridge.
=====================================================
One source of truth for every writable location. Three deployment targets:

  HA add-on   /data, /media/oak_recordings, /models      (Supervisor mounts)
  Portable    <exe folder>/data, /recordings, /models     (travels on a stick)
  Source      ~/.local/share/oak-camera  or  %LOCALAPPDATA%\OakCamera

Every location accepts an environment override so the launcher can place data
anywhere without a code change:

  OAK_DATA_DIR  OAK_RECORDINGS_DIR  OAK_MODELS_DIR  OAK_LOG_DIR  OAK_BIN_DIR
"""

import os
import sys
import tempfile

APP_NAME = "OakCamera"

# Set once on first call so every thread agrees on the layout.
_resolved: dict[str, str] = {}


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def is_ha_addon() -> bool:
    """True when the Home Assistant Supervisor started this process.

    The Supervisor writes /data/options.json before launch. That file is a
    stronger signal than /data alone, because a plain Linux host may own /data.
    """
    return os.path.isfile("/data/options.json")


def app_dir() -> str:
    """The folder that holds the executable, or the repository src folder."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir() -> str:
    """The folder that holds bundled read-only resources.

    PyInstaller onefile unpacks to a new temporary folder on every launch and
    exposes it as sys._MEIPASS. Onedir and source runs use the app folder.
    """
    return getattr(sys, "_MEIPASS", app_dir())


def _writable(path: str) -> bool:
    """Create path and confirm this process can write a file inside it."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _user_dir() -> str:
    """Per-user application data folder for this platform."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        return os.path.join(base, APP_NAME)
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "oak-camera")


def _resolve(key: str, env_var: str, ha_path: str, portable_name: str) -> str:
    """Pick a writable folder for one role and remember the choice.

    Order: environment override, Home Assistant mount, folder beside the
    executable, per-user folder. The portable folder comes before the per-user
    folder so a USB stick carries its own data. It is skipped when the user
    unzipped into a read-only location such as C:\Program Files.
    """
    if key in _resolved:
        return _resolved[key]

    candidates = []
    override = os.environ.get(env_var, "").strip()
    if override:
        candidates.append(override)
    elif is_ha_addon():
        candidates.append(ha_path)
    else:
        candidates.append(os.path.join(app_dir(), portable_name))
        candidates.append(os.path.join(_user_dir(), portable_name))

    for path in candidates:
        if _writable(path):
            _resolved[key] = path
            return path

    # Last resort: the system temporary folder is always writable. Data does
    # not survive a reboot there, so the launcher logs a warning.
    fallback = os.path.join(tempfile.gettempdir(), APP_NAME, portable_name)
    os.makedirs(fallback, exist_ok=True)
    _resolved[key] = fallback
    return fallback


def data_dir() -> str:
    """Settings and other small state that must survive an upgrade."""
    return _resolve("data", "OAK_DATA_DIR", "/data", "data")


def recordings_dir() -> str:
    """Motion clips. This folder grows, so the storage monitor watches it."""
    return _resolve("recordings", "OAK_RECORDINGS_DIR",
                    "/media/oak_recordings", "recordings")


def models_dir() -> str:
    """Neural network archives and the DepthAI model cache."""
    return _resolve("models", "OAK_MODELS_DIR", "/models", "models")


def log_dir() -> str:
    """Rotating log files. Shares the data folder unless overridden."""
    override = os.environ.get("OAK_LOG_DIR", "").strip()
    if override:
        return _resolve("log", "OAK_LOG_DIR", "/data", "logs")
    return data_dir()


def bin_dir() -> str:
    """Stable folder for child executables such as mediamtx and ffmpeg.

    A onefile bundle unpacks to a new temporary path on every launch. Windows
    Firewall ties its rules to the binary path, so a child started from that
    path prompts the user on every launch. Copying the child binaries here once
    gives them a fixed path and the firewall rule then persists.
    """
    return _resolve("bin", "OAK_BIN_DIR", "/usr/local/bin", "bin")


def describe() -> str:
    """One line per resolved location, for the startup log."""
    mode = "HA add-on" if is_ha_addon() else ("portable" if is_frozen() else "source")
    return "\n".join([
        f"Deployment mode: {mode}",
        f"  settings:   {data_dir()}",
        f"  recordings: {recordings_dir()}",
        f"  models:     {models_dir()}",
        f"  logs:       {log_dir()}",
        f"  binaries:   {bin_dir()}",
    ])
