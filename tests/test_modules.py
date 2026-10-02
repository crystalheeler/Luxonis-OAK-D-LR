"""
Release check for the support modules. Runs without depthai or a camera.
========================================================================
Covers oak_paths, oak_logging, oak_runtime, oak_launcher and oak_tray. It does
not cover oak_bridge, which needs depthai and the camera.

    python tests/test_modules.py

Exits 1 on the first failing group, and prints every result.
"""
import json
import logging
import os
import shutil
import socket
import sys
import tempfile

REPO = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                       else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

WORK = tempfile.mkdtemp(prefix="oak_test_")
fails = []


def check(label, cond, detail=""):
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {detail}")
        fails.append(label)


# ============================================================ oak_paths
print("\n[oak_paths]")
# Force the portable branch by pointing every override at the work folder.
os.environ["OAK_DATA_DIR"]       = os.path.join(WORK, "data")
os.environ["OAK_RECORDINGS_DIR"] = os.path.join(WORK, "recordings")
os.environ["OAK_MODELS_DIR"]     = os.path.join(WORK, "models")
os.environ["OAK_BIN_DIR"]        = os.path.join(WORK, "bin")

import oak_paths

check("data_dir honours the override", oak_paths.data_dir() == os.path.join(WORK, "data"),
      oak_paths.data_dir())
check("data_dir was created", os.path.isdir(oak_paths.data_dir()))
check("recordings_dir was created", os.path.isdir(oak_paths.recordings_dir()))
check("models_dir was created", os.path.isdir(oak_paths.models_dir()))
check("bin_dir was created", os.path.isdir(oak_paths.bin_dir()))
check("log_dir falls back to data_dir", oak_paths.log_dir() == oak_paths.data_dir())
check("is_ha_addon is false off Home Assistant", oak_paths.is_ha_addon() is False)
check("is_frozen is false in a source run", oak_paths.is_frozen() is False)
check("describe names the mode", "Deployment mode: source" in oak_paths.describe(),
      oak_paths.describe())

# An unwritable target must fall through, not raise.
if sys.platform == "win32":
    bogus = "Z:\\definitely\\not\\mounted\\oak"
else:
    bogus = "/proc/definitely-not-writable/oak"
oak_paths._resolved.pop("probe", None)
got = oak_paths._resolve("probe", "OAK_PROBE_DIR", bogus, "probe")
check("an unwritable candidate falls back", os.path.isdir(got), got)

# ============================================================ oak_logging
print("\n[oak_logging]")
import oak_logging

log_file = oak_logging.setup_logging(capture_streams=False)
logging.getLogger("test").info("hello from the test")
for h in logging.getLogger().handlers:
    h.flush()
check("setup_logging returns a path", log_file.endswith("oak_camera.log"), log_file)
check("the log file exists", os.path.isfile(log_file))
body = open(log_file, encoding="utf-8").read()
check("the message reached the file", "hello from the test" in body)
check("log_path matches", oak_logging.log_path() == log_file)

# The stream shim must survive a print when stdout is None.
shim = oak_logging._StreamToLog(logging.getLogger("shimtest"), logging.INFO)
real_stdout, sys.stdout = sys.stdout, shim
try:
    print("printed through the shim")
finally:
    sys.stdout = real_stdout
for h in logging.getLogger().handlers:
    h.flush()
body = open(log_file, encoding="utf-8").read()
check("print through the shim reaches the log", "printed through the shim" in body)
check("the shim reports it is not a terminal", shim.isatty() is False)

# ============================================================ oak_runtime
print("\n[oak_runtime]")
import oak_runtime

check("_exe_name adds .exe only on Windows",
      oak_runtime._exe_name("mediamtx") ==
      ("mediamtx.exe" if sys.platform == "win32" else "mediamtx"))
check("_same_path matches an equivalent path",
      oak_runtime._same_path(WORK, os.path.join(WORK, ".")))

# Pick a free port. The production port may be held by a real instance on
# this machine, and the guard working is not a test failure.
_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_probe.bind(("127.0.0.1", 0))
LOCK_PORT = _probe.getsockname()[1]
_probe.close()

got_lock = oak_runtime.acquire_single_instance(port=LOCK_PORT)
check("the first instance takes the lock", got_lock is True)
check("a second instance is refused",
      oak_runtime.acquire_single_instance(0.0, port=LOCK_PORT) is False)
oak_runtime.release_single_instance()
check("the lock is reusable after release",
      oak_runtime.acquire_single_instance(port=LOCK_PORT) is True)
oak_runtime.release_single_instance()
check("the production marker port is 8764",
      oak_runtime.SINGLE_INSTANCE_PORT == 8764, oak_runtime.SINGLE_INSTANCE_PORT)

# A fake binary in bin_dir must win over PATH.
fake = os.path.join(oak_paths.bin_dir(), oak_runtime._exe_name("mediamtx"))
with open(fake, "w") as f:
    f.write("#!/bin/sh\nexit 0\n")
check("resolve_binary finds the staged copy",
      oak_runtime.resolve_binary("mediamtx") == fake, oak_runtime.resolve_binary("mediamtx"))
check("resolve_binary returns None when absent",
      oak_runtime.resolve_binary("definitely-not-a-real-binary-xyz") is None)
check("restart_wait_seconds is zero on a cold start",
      oak_runtime.restart_wait_seconds() == 0.0)

# A windowed parent has no console to share, so Windows opens a new console
# window for every console child. 3.0.0 shipped with two of them on screen.
flags = oak_runtime.child_creation_flags()
if sys.platform == "win32":
    import subprocess as _sp
    check("child_creation_flags hides the console on Windows",
          flags == _sp.CREATE_NO_WINDOW, hex(flags))
else:
    check("child_creation_flags is zero off Windows", flags == 0, flags)

# Guard the two spawn sites themselves, because the helper only helps when it
# is actually passed.
for _mod, _name in (("oak_bridge.py", "ffmpeg"), ("oak_launcher.py", "mediamtx")):
    _src = open(os.path.join(REPO, "src", _mod), encoding="utf-8").read()
    _spawns = _src.count("subprocess.Popen(")
    _flagged = _src.count("creationflags=oak_runtime.child_creation_flags()")
    check(f"{_name} spawns with creationflags", _flagged >= 1,
          f"{_flagged} flagged of {_spawns} Popen calls")
os.environ[oak_runtime.RESTART_ENV] = "1"
check("restart_wait_seconds is positive on a restart",
      oak_runtime.restart_wait_seconds() > 0)
del os.environ[oak_runtime.RESTART_ENV]

# ============================================================ oak_launcher
print("\n[oak_launcher]")
import oak_launcher

# Clear the variables apply_config sets, so defaults are observable.
for _k, env_var, _d in oak_launcher.OPTION_MAP:
    os.environ.pop(env_var, None)

cfg_path = os.path.join(oak_paths.data_dir(), oak_launcher.CONFIG_NAME)
shutil.copy(os.path.join(REPO, "windows", "oak_config.yaml"), cfg_path)
cfg, source = oak_launcher.load_config()
check("load_config finds oak_config.yaml", source == cfg_path, source)
check("load_config parsed the keys", "camera_ip" in cfg and "fps" in cfg, list(cfg)[:4])

oak_launcher.apply_config(cfg)
check("FPS reached the environment", os.environ.get("FPS") == "15", os.environ.get("FPS"))
check("MJPEG_PORT reached the environment", os.environ.get("MJPEG_PORT") == "8765")
check("a boolean renders lowercase",
      os.environ.get("FILENAME_TAG_OBJECTS") == "true",
      os.environ.get("FILENAME_TAG_OBJECTS"))
check("DETECTION_MODEL reached the environment",
      os.environ.get("DETECTION_MODEL") == "yolov6-nano")

# An existing variable must win over the file.
os.environ["FPS"] = "22"
oak_launcher.apply_config(cfg)
check("an existing variable is not overwritten", os.environ.get("FPS") == "22")

# The Home Assistant branch: options.json wins when present.
ha_dir = os.path.join(WORK, "fake_ha")
os.makedirs(ha_dir, exist_ok=True)
opts = os.path.join(ha_dir, "options.json")
with open(opts, "w") as f:
    json.dump({"camera_ip": "10.0.0.5", "fps": 20}, f)
real_ha_path = oak_launcher.HA_OPTIONS_PATH
oak_launcher.HA_OPTIONS_PATH = opts
cfg2, source2 = oak_launcher.load_config()
oak_launcher.HA_OPTIONS_PATH = real_ha_path
check("options.json is preferred", source2 == opts, source2)
check("options.json values are read",
      cfg2.get("camera_ip") == "10.0.0.5" and cfg2.get("fps") == 20, cfg2)

# mediamtx config generation must track the configured port.
mtx = oak_launcher.write_mediamtx_config(9100)
body = open(mtx, encoding="utf-8").read()
check("the generated config exists", os.path.isfile(mtx))
check("rtspAddress tracks the port", "rtspAddress: :9100" in body, body.split("\n")[3])
check("the publisher path is defined", "source: publisher" in body)
import yaml
parsed = yaml.safe_load(body)
check("the generated config is valid YAML", parsed.get("rtspAddress") == ":9100", parsed)

check("stop_mediamtx is safe with no child", oak_launcher.stop_mediamtx() is None)

# ============================================================ oak_tray
print("\n[oak_tray]")
try:
    import oak_tray
    check("oak_tray imports", True)
    target = oak_tray._autostart_target()
    check("the autostart target is quoted", target.startswith('"'), target)
    check("the autostart target names python or the exe",
          "python" in target.lower() or "oakcamera" in target.lower(), target)
    img_ok = True
    try:
        im = oak_tray._build_image()
        img_ok = im.size == (oak_tray.ICON_SIZE, oak_tray.ICON_SIZE)
    except Exception as e:
        img_ok = f"raised {e}"
    check("the tray image renders", img_ok is True, img_ok)
except ImportError as e:
    print(f"  SKIP  oak_tray needs pystray: {e}")

# ============================================================ settings page
print(chr(10) + "[settings_page]")
import settings_page

_on  = settings_page.build_settings_html(show_shutdown=True)
_off = settings_page.build_settings_html(show_shutdown=False)
check("the standalone page offers Shut down", "Shut down" in _on)
check("the add-on page hides Shut down", "Shut down" not in _off)
check("hiding it removes exactly one button",
      _off.count("<button") == _on.count("<button") - 1,
      f"{_on.count('<button')} vs {_off.count('<button')}")
check("every other control survives",
      all(t in _off for t in ("Save &amp; Apply", "Reload", "Reset defaults")))

# ============================================================ icon
print("\n[icon]")
ico = os.path.join(REPO, "windows", "oak_camera.ico")
check("the icon file exists", os.path.isfile(ico))
if os.path.isfile(ico):
    from PIL import Image
    with Image.open(ico) as im:
        sizes = sorted({s[0] for s in im.info.get("sizes", [im.size])})
    check("the icon holds 16 and 256 px", 16 in sizes and 256 in sizes, sizes)

# ============================================================
shutil.rmtree(WORK, ignore_errors=True)
print("\n" + "=" * 58)
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
