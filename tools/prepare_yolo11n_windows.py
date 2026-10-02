"""
YOLO11n RVC2 Preparation Script — Run this on your Windows PC ONCE
===================================================================
This script downloads YOLO11n, converts it to an RVC2-compatible NNArchive,
and saves yolo11n.tar.xz in the same folder as this script.

Copy that file into your oak_camera_app folder alongside the other files,
then do the normal App store -> Check for updates -> Update flow.

Requirements (install with pip):
    pip install ultralytics blobconverter

    For luxonis-tools (YOLO head patching):
    pip install "luxonis-tools @ git+https://github.com/luxonis/tools.git"

Usage:
    python prepare_yolo11n_windows.py
"""

import os
import sys
import subprocess
import shutil
import glob
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "yolo11n.tar.xz")

print("=" * 60)
print("YOLO11n RVC2 Preparation Script")
print("=" * 60)

# Check requirements
missing = []
try:
    import ultralytics
    print(f"  ultralytics: {ultralytics.__version__} OK")
except ImportError:
    missing.append("ultralytics")

try:
    import blobconverter
    print(f"  blobconverter: OK")
except ImportError:
    missing.append("blobconverter")

if missing:
    print(f"\nERROR: Missing packages: {', '.join(missing)}")
    print(f"Install with: pip install {' '.join(missing)}")
    sys.exit(1)

work_dir = tempfile.mkdtemp(prefix="yolo11n_")
print(f"\nWorking directory: {work_dir}")

try:
    # Step 1: Download yolo11n.pt
    print("\nStep 1: Downloading yolo11n.pt from Ultralytics...")
    os.chdir(work_dir)
    from ultralytics import YOLO
    model = YOLO("yolo11n.pt")
    pt_path = os.path.abspath("yolo11n.pt")
    print(f"  Saved to: {pt_path}")

    # Step 2: Convert using luxonis tools CLI
    print("\nStep 2: Converting with Luxonis tools (patches YOLO detection head)...")
    print("  (This calls blobconverter.luxonis.com — internet required)")
    try:
        result = subprocess.run(
            ["tools", pt_path,
             "--imgsz", "512 288",
             "--use-rvc2",
             "--version", "yolo11"],
            capture_output=False,
            cwd=work_dir
        )
        if result.returncode != 0:
            raise RuntimeError("tools conversion failed")
    except FileNotFoundError:
        print("\n  'tools' CLI not found. Trying alternative: luxonis_tools module...")
        result = subprocess.run(
            [sys.executable, "-m", "tools", pt_path,
             "--imgsz", "512 288",
             "--use-rvc2",
             "--version", "yolo11"],
            capture_output=False,
            cwd=work_dir
        )
        if result.returncode != 0:
            raise RuntimeError("tools module conversion failed")

    # Step 3: Find output archive
    print("\nStep 3: Locating output...")
    archives = glob.glob(os.path.join(work_dir, "**", "*.tar.xz"), recursive=True)

    if archives:
        shutil.copy(archives[0], OUTPUT_PATH)
        size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
        print(f"\nSUCCESS! Output: {OUTPUT_PATH} ({size_mb:.1f} MB)")
        print("\nNext steps:")
        print("  1. Make sure yolo11n.tar.xz is in your oak_camera_app folder")
        print("  2. Copy the oak_camera_app folder to your HA addons share")
        print("  3. App store -> Check for updates -> Update")
    else:
        print("\nERROR: Could not find output .tar.xz")
        print(f"Check {work_dir} manually for output files")
        sys.exit(1)

finally:
    # Cleanup
    try:
        shutil.rmtree(work_dir)
    except Exception:
        pass
