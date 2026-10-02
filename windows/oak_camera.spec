# PyInstaller spec for the portable Windows executable.
# -*- mode: python ; coding: utf-8 -*-
#
# Produces ONE file: dist/OakCamera.exe
#
#   onefile    the user gets a single program to double-click
#   windowed   no console window, so every message goes to oak_camera.log
#
# Build from the repository root:
#   pyinstaller --clean --noconfirm windows/oak_camera.spec
#
# mediamtx.exe and ffmpeg.exe are bundled when present in windows/bin/. The
# release workflow downloads them there. ffmpeg is optional: without it the
# RTSP stream turns off and every other output keeps working.

import os
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

BIN_DIR = os.path.join("windows", "bin")

# --- child executables --------------------------------------------------------
# These land at the bundle root. oak_runtime.stage_binaries copies them to a
# fixed folder on first run, so Windows Firewall rules survive a restart.
binaries = []
for name in ("mediamtx.exe", "ffmpeg.exe"):
    path = os.path.join(BIN_DIR, name)
    if os.path.isfile(path):
        binaries.append((path, "."))
        print(f"spec: bundling {name}")
    else:
        print(f"spec: {name} not found in {BIN_DIR} — skipping")

datas = [
    # Default config. oak_launcher writes nothing over an existing copy beside
    # the executable, so a user edit survives an upgrade.
    (os.path.join("windows", "oak_config.yaml"), "."),
]
hiddenimports = []

# --- DepthAI ------------------------------------------------------------------
# Ships a compiled extension plus data files that PyInstaller does not find on
# its own. collect_all pulls the package, its libraries and its data together.
for package in ("depthai", "depthai_nodes"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas        += pkg_datas
        binaries     += pkg_binaries
        hiddenimports += pkg_hidden
        print(f"spec: collected {package}")
    except Exception as exc:
        print(f"spec: could not collect {package}: {exc}")

# --- OpenCV -------------------------------------------------------------------
# cv2.VideoWriter writes the motion clips with the mp4v codec, and that needs
# opencv_videoio_ffmpeg*.dll. Some PyInstaller versions miss it, and the failure
# is quiet: recording stops while the rest of the program runs. Collect the
# OpenCV libraries explicitly so a clean machine still records.
try:
    binaries += collect_dynamic_libs("cv2")
    print("spec: collected cv2 dynamic libraries")
except Exception as exc:
    print(f"spec: could not collect cv2 libraries: {exc}")

hiddenimports += [
    "pystray._win32",       # pystray picks its backend at runtime
    "PIL._tkinter_finder",
]

a = Analysis(
    ["src/oak_launcher.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trim the bundle. None of these are imported at runtime, and tkinter and
    # matplotlib alone add roughly 40 MB.
    excludes=[
        "tkinter", "matplotlib", "scipy", "pandas", "pytest",
        "IPython", "notebook", "setuptools._distutils",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OakCamera",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX raises antivirus false positives
    runtime_tmpdir=None,
    console=False,      # windowed: oak_logging writes the log file instead
    disable_windowed_traceback=False,
    icon=os.path.join("windows", "oak_camera.ico")
         if os.path.isfile(os.path.join("windows", "oak_camera.ico")) else None,
    version=os.path.join("windows", "version_info.txt")
            if os.path.isfile(os.path.join("windows", "version_info.txt")) else None,
)
