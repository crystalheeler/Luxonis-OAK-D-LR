"""
System tray icon for the portable Windows build.
==================================================
A windowed executable has no console, so the user cannot press Ctrl-C and
cannot read the log. The tray icon supplies both, and it replaces the batch
files an installer would otherwise provide.

Menu:
  Open settings      the existing web panel on port 8767
  View log           opens oak_camera.log in the default text editor
  Open data folder   recordings, settings and the log
  Start with Windows a registry Run entry, toggled on and off
  Restart            the same handover the settings panel Restart uses
  Quit               stops every thread and every child process

pystray and Pillow are optional. The launcher catches an ImportError and keeps
running without a tray, because the settings panel can also stop the program.
"""

import logging
import os
import sys
import threading
import webbrowser

import oak_paths
import oak_logging
import oak_runtime

log = logging.getLogger("oak-tray")

RUN_KEY_PATH  = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_KEY_NAME  = "OakCamera"
ICON_SIZE     = 64

_icon = None


# ==============================================================================
# Start with Windows, through the registry Run key
# ==============================================================================

def _autostart_target() -> str:
    """The command the Run key stores. Quoted, because paths hold spaces."""
    if oak_paths.is_frozen():
        return f'"{os.path.abspath(sys.executable)}"'
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oak_launcher.py")
    return f'"{os.path.abspath(sys.executable)}" "{script}"'


def autostart_enabled() -> bool:
    """True when the Run key points at this executable."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, RUN_KEY_NAME)
        return value == _autostart_target()
    except (ImportError, OSError):
        return False


def set_autostart(enable: bool) -> None:
    """Add or remove the Run key. Needs no administrator rights."""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            if enable:
                winreg.SetValueEx(key, RUN_KEY_NAME, 0, winreg.REG_SZ,
                                  _autostart_target())
                log.info("Enabled start with Windows")
            else:
                try:
                    winreg.DeleteValue(key, RUN_KEY_NAME)
                    log.info("Disabled start with Windows")
                except FileNotFoundError:
                    pass
    except (ImportError, OSError) as e:
        log.error(f"Could not change the start with Windows setting: {e}")


# ==============================================================================
# Icon artwork
# ==============================================================================

def _build_image():
    """Draw a camera aperture. Avoids shipping a separate image file."""
    from PIL import Image, ImageDraw

    size  = ICON_SIZE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(image)

    margin = 4
    # Dark body with a bright ring, so the icon reads on light and dark taskbars.
    draw.ellipse([margin, margin, size - margin, size - margin],
                 fill=(24, 28, 34, 255), outline=(255, 255, 255, 255), width=3)
    # Aperture blades.
    centre = size / 2
    radius = centre - margin - 8
    draw.ellipse([centre - radius, centre - radius, centre + radius, centre + radius],
                 outline=(0, 200, 90, 255), width=4)
    draw.ellipse([centre - 6, centre - 6, centre + 6, centre + 6],
                 fill=(0, 200, 90, 255))
    return image


# ==============================================================================
# Menu actions
# ==============================================================================

def _open_path(path: str | None) -> None:
    """Open a file or folder with the platform default handler."""
    if not path or not os.path.exists(path):
        log.warning(f"Nothing to open at {path}")
        return
    try:
        if sys.platform == "win32":
            os.startfile(path)      # noqa: S606 - the path is ours
        else:
            webbrowser.open(f"file://{path}")
    except OSError as e:
        log.error(f"Could not open {path}: {e}")


def start(bridge) -> None:
    """Create the tray icon and run its message loop on a background thread.

    Takes the oak_bridge module so Quit and Restart reuse the same shutdown
    path as the settings panel.
    """
    global _icon

    import pystray
    from pystray import MenuItem, Menu

    settings_url = f"http://localhost:{bridge.INGRESS_PORT}/"

    def on_settings(icon, item):
        webbrowser.open(settings_url)

    def on_log(icon, item):
        _open_path(oak_logging.log_path())

    def on_data(icon, item):
        _open_path(oak_paths.data_dir())

    def on_recordings(icon, item):
        _open_path(oak_paths.recordings_dir())

    def on_autostart(icon, item):
        set_autostart(not autostart_enabled())

    def on_restart(icon, item):
        icon.stop()
        oak_runtime.restart_process(bridge.shutdown_children)

    def on_quit(icon, item):
        icon.stop()
        bridge.request_shutdown()

    menu = Menu(
        MenuItem("Open settings", on_settings, default=True),
        MenuItem("View log", on_log),
        Menu.SEPARATOR,
        MenuItem("Open data folder", on_data),
        MenuItem("Open recordings folder", on_recordings),
        Menu.SEPARATOR,
        MenuItem("Start with Windows", on_autostart,
                 checked=lambda item: autostart_enabled()),
        Menu.SEPARATOR,
        MenuItem("Restart", on_restart),
        MenuItem("Quit", on_quit),
    )

    _icon = pystray.Icon("oak_camera", _build_image(), "OAK-D LR Camera", menu)

    # pystray needs its own message loop. Run it on a daemon thread so the
    # bridge keeps the main thread for signal handling.
    threading.Thread(target=_icon.run, name="tray", daemon=True).start()
    log.info(f"Tray icon started — settings at {settings_url}")


def stop() -> None:
    """Remove the tray icon. Safe to call when no icon exists."""
    global _icon
    if _icon is not None:
        try:
            _icon.stop()
        except Exception:
            pass
        _icon = None
