"""
Launcher for the OAK camera bridge. One entry point, three deployment targets.
===============================================================================
This file replaces the old run.sh, which read its settings through bashio and
therefore only ran inside the Home Assistant Supervisor.

Config sources, in priority order:

  1 /data/options.json        written by the Home Assistant Supervisor
  2 oak_config.yaml           beside the executable, for the portable build
  3 the defaults below

Every value becomes an environment variable, which is the interface oak_bridge
already expects. oak_bridge therefore needs no knowledge of how it was started.

The launcher also owns mediamtx: it writes the config, starts the process,
copies its output into the log, and stops it on shutdown.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import time

# The bundle puts every module in one folder. A source checkout runs from src/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oak_paths
import oak_logging
import oak_runtime

log = logging.getLogger("oak-launcher")

CONFIG_NAME     = "oak_config.yaml"
HA_OPTIONS_PATH = "/data/options.json"

# Option name in the config file, environment variable oak_bridge reads,
# and the default. The old run.sh also exported DETECT_* and CONFIDENCE_*
# variables. oak_bridge ignores them, because the settings panel is the only
# source of per-object thresholds, so they are gone.
OPTION_MAP = (
    ("camera_ip",               "CAMERA_IP",               ""),
    ("mjpeg_port",              "MJPEG_PORT",              8765),
    ("fps",                     "FPS",                     15),
    ("detection_model",         "DETECTION_MODEL",         "yolov6-nano"),
    ("filename_tag_objects",    "FILENAME_TAG_OBJECTS",    True),
    ("storage_alert_enabled",   "STORAGE_ALERT_ENABLED",   True),
    ("storage_alert_threshold", "STORAGE_ALERT_THRESHOLD", 50),
    ("ha_url",                  "HA_URL",                  "http://homeassistant.local:8123"),
    ("ha_token",                "HA_TOKEN",                ""),
)

# Folders the config file may redirect. These reach oak_paths, not oak_bridge.
PATH_OPTION_MAP = (
    ("recordings_dir", "OAK_RECORDINGS_DIR"),
    ("data_dir",       "OAK_DATA_DIR"),
    ("models_dir",     "OAK_MODELS_DIR"),
)

_mediamtx_proc: subprocess.Popen | None = None


# ==============================================================================
# Config loading
# ==============================================================================

def _find_config_file() -> str | None:
    """Return the path of oak_config.yaml, searching the usual folders."""
    for folder in (oak_paths.app_dir(), oak_paths.data_dir(), oak_paths.bundle_dir()):
        candidate = os.path.join(folder, CONFIG_NAME)
        if os.path.isfile(candidate):
            return candidate
    return None


def load_config() -> tuple[dict, str]:
    """Return the settings dictionary and a label naming where it came from."""
    if os.path.isfile(HA_OPTIONS_PATH):
        try:
            with open(HA_OPTIONS_PATH, encoding="utf-8") as f:
                return json.load(f), HA_OPTIONS_PATH
        except (OSError, ValueError) as e:
            log.error(f"Could not read {HA_OPTIONS_PATH}: {e} — using defaults")
            return {}, "defaults"

    path = _find_config_file()
    if path is None:
        return {}, "defaults"

    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}), path
    except ImportError:
        log.error("PyYAML is not installed — using defaults")
        return {}, "defaults"
    except (OSError, ValueError) as e:
        log.error(f"Could not read {path}: {e} — using defaults")
        return {}, "defaults"


def _as_env(value) -> str:
    """Render a config value the way oak_bridge parses it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def apply_config(cfg: dict) -> None:
    """Copy every option into the environment, unless already set.

    An existing environment variable wins, so a user can override one setting
    on the command line without editing the config file.
    """
    for key, env_var in PATH_OPTION_MAP:
        value = cfg.get(key)
        if value and not os.environ.get(env_var):
            os.environ[env_var] = str(value)

    for key, env_var, default in OPTION_MAP:
        if os.environ.get(env_var):
            continue
        value = cfg.get(key, default)
        if value is None:
            value = default
        os.environ[env_var] = _as_env(value)


# ==============================================================================
# mediamtx
# ==============================================================================

def write_mediamtx_config(rtsp_port: int) -> str:
    """Generate the mediamtx config and return its path.

    The old docker/mediamtx.yml hardcoded port 8765 while mjpeg_port was
    configurable. Setting mjpeg_port to anything else broke the RTSP stream,
    because ffmpeg published to the new port and mediamtx still listened on
    8765. Generating the file keeps the two in step.
    """
    path = os.path.join(oak_paths.data_dir(), "mediamtx.yml")
    body = "\n".join([
        "# Generated by oak_launcher.py on every start. Edits are lost.",
        "logLevel: info",
        "logDestinations: [stdout]",
        f"rtspAddress: :{rtsp_port}",
        "",
        "# Room for the dashboard viewer, the recorder and any other client.",
        "writeQueueSize: 512",
        "",
        "paths:",
        "  stream:",
        "    source: publisher",
        "",
    ])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return path


def start_mediamtx(rtsp_port: int) -> subprocess.Popen | None:
    """Start the RTSP server. Return None when the binary is missing."""
    global _mediamtx_proc

    exe = oak_runtime.resolve_binary("mediamtx")
    if exe is None:
        log.warning("mediamtx not found — RTSP stream disabled. "
                    "The MJPEG feed, snapshots and recording still run.")
        return None

    cfg = write_mediamtx_config(rtsp_port)
    log.info(f"Starting mediamtx on port {rtsp_port}")
    try:
        _mediamtx_proc = subprocess.Popen(
            [exe, cfg], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=oak_runtime.child_creation_flags())
    except OSError as e:
        log.error(f"Could not start mediamtx: {e}")
        return None

    # mediamtx logs to stdout, which goes nowhere without a console.
    oak_logging.drain_pipe(_mediamtx_proc.stdout, "mediamtx")
    return _mediamtx_proc


def stop_mediamtx() -> None:
    """Stop the RTSP server. Registered as a bridge cleanup hook."""
    global _mediamtx_proc
    if _mediamtx_proc is None:
        return
    log.info("Stopping mediamtx")
    try:
        _mediamtx_proc.terminate()
        _mediamtx_proc.wait(timeout=5)
    except Exception:
        try:    _mediamtx_proc.kill()
        except Exception: pass
    _mediamtx_proc = None


# ==============================================================================
# Entry point
# ==============================================================================

def _want_tray() -> bool:
    """True when a system tray icon makes sense.

    The tray is the only way to quit a windowed build, so it matters on the
    portable Windows executable. The add-on and a console run do not need it.
    """
    if oak_paths.is_ha_addon():
        return False
    if os.environ.get("OAK_NO_TRAY", "").strip() == "1":
        return False
    return sys.platform == "win32" and oak_paths.is_frozen()


def _want_browser(cfg: dict) -> bool:
    """True when the settings page should open at startup.

    Never in the add-on, where Home Assistant owns the sidebar panel. Never
    when the user turns it off in the config.
    """
    if oak_paths.is_ha_addon():
        return False
    if os.environ.get("OAK_NO_BROWSER", "").strip() == "1":
        return False
    return bool(cfg.get("open_settings_on_start", True))


def _open_settings_page(port: int) -> None:
    """Open the settings page after the server has had time to bind."""
    import threading
    import webbrowser

    url = f"http://localhost:{port}/"

    def _later():
        # ingress_thread binds a few seconds after start on a cold run.
        for _ in range(30):
            time.sleep(1)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                continue
        else:
            log.warning(f"Settings page did not open: nothing listening on {port}")
            return
        log.info(f"Opening the settings page at {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            log.warning(f"Could not open a browser: {e} — open {url} by hand")

    threading.Thread(target=_later, name="open-browser", daemon=True).start()


def main() -> int:
    in_addon = oak_paths.is_ha_addon()

    # The Supervisor already captures stdout and shows it in the add-on log,
    # so the add-on keeps its streams and also writes the rotating file.
    oak_logging.setup_logging(capture_streams=not in_addon)

    log.info("=" * 62)
    log.info("OAK-D LR Camera bridge")
    log.info(oak_paths.describe())

    # A second copy would fight over ports 8765 to 8767 and over the camera.
    # A restart waits, because the outgoing process still holds the marker.
    if not oak_runtime.acquire_single_instance(oak_runtime.restart_wait_seconds()):
        log.error("Another copy of OAK Camera is already running — exiting. "
                  f"Open the settings page at http://localhost:8767/")
        return 1

    cfg, source = load_config()
    log.info(f"Config source: {source}")
    apply_config(cfg)

    if not os.environ.get("CAMERA_IP"):
        log.warning("camera_ip is empty — DepthAI will search for a USB device. "
                    "Set camera_ip to the OAK-D LR address for PoE.")

    # Copy mediamtx and ffmpeg to a fixed folder. A onefile bundle unpacks to a
    # new temporary path on every launch, and Windows Firewall keys its rules on
    # the path, so without this the user answers a prompt on every launch.
    if oak_paths.is_frozen():
        oak_runtime.stage_binaries()

    rtsp_port = int(os.environ.get("MJPEG_PORT", "8765"))
    start_mediamtx(rtsp_port)

    # Import the bridge only now, so logging and every path is already set.
    import oak_bridge
    oak_bridge.register_cleanup(stop_mediamtx)

    if _want_tray():
        try:
            import oak_tray
            oak_tray.start(oak_bridge)
        except Exception as e:
            log.warning(f"Tray icon unavailable: {e} — "
                        f"use the settings page to stop the program")

    # A windowed build shows no window, and Windows hides a new tray icon in
    # the overflow area. Without this the program looks like it did nothing.
    # Opening the settings page gives the user something to see.
    if _want_browser(cfg):
        _open_settings_page(oak_bridge.INGRESS_PORT)

    oak_bridge.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
