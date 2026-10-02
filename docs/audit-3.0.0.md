# Audit note — 3.0.0

Companion to the 3.0.0 changelog entry. It holds the evidence, the measurements
and the design reasons that the changelog leaves out, and it names every check
that did not run.

Owner: CrystalHeeler. Date: 2026-10-02.

---

## 1. Scope

3.0.0 makes one source tree serve three deployments: the Home Assistant add-on,
a portable Windows executable, and a source run on Linux.

| Metric | Value |
|---|---|
| Python in `src/` | 2,458 lines across 7 files |
| New modules | 5 (`oak_launcher`, `oak_paths`, `oak_logging`, `oak_runtime`, `oak_tray`) |
| Changed lines in `oak_bridge.py` | about 50 of 1,085 |
| Files deleted | 3 (`run.sh`, the root `config.yaml`, `docker/mediamtx.yml`) |
| Release checks | 45, all passing |

The 8 thread pipeline, the DepthAI code, the detection logic and the settings
panel are unchanged.

---

## 2. Design reasons

### 2.1 Why one launcher replaced run.sh

`run.sh` read all 30 of its settings through bashio, a helper that exists only
inside the Home Assistant Supervisor. A standalone build could not run it.

bashio reads `/data/options.json`. `oak_launcher.py` reads the same file
directly, so the Supervisor interface does not change. Off Home Assistant the
launcher falls back to `oak_config.yaml` beside the executable.

The alternative was two launchers, one per deployment. Both would hold the same
30 option names, and they would drift apart.

### 2.2 Why the add-on dropped its Dockerfile

A Home Assistant add-on builds with its own folder as the Docker context. A
`Dockerfile` under `addon/oak_camera/` therefore cannot `COPY` the Python source
from the repository root.

Two published add-ons solve this the same way, with a prebuilt image: go2rtc at
[AlexxIT/hassio-addons](https://github.com/AlexxIT/hassio-addons) uses
`image: alexxit/go2rtc`, and Frigate at
[frigate-hass-addons](https://github.com/blakeblackshear/frigate-hass-addons)
uses `image: ghcr.io/blakeblackshear/frigate`. This release follows that
pattern.

Dropping the Home Assistant base image also drops s6-overlay. That is
acceptable because the restart path no longer depends on a supervisor. See 3.2.

### 2.3 Why child binaries copy to a fixed folder

A PyInstaller onefile bundle unpacks to a new `%TEMP%` folder on every launch.
Windows Firewall keys its rules to the binary path, so
[mediamtx](https://github.com/bluenviron/mediamtx) started from that path would
raise a new firewall prompt every launch.

`oak_runtime.stage_binaries` copies each child binary to a fixed folder on first
run. The user then answers the prompt one time.

### 2.4 Why the build is windowed, and what that forces

A console window on a double-clicked camera service is noise. `console=False`
removes it, and that removes three things the program depended on:

| Lost | Replacement |
|---|---|
| Visible log output | `oak_logging` writes a rotating file |
| Ctrl-C to quit | Tray icon Quit, plus a Shut down button on the settings page |
| Working `sys.stdout` | A shim, because PyInstaller sets both streams to `None` |

The third item is not theoretical. `src/download_models.py` prints on lines 15
and 18. Without the shim a first-run model download raises `AttributeError` on
`None.write`.

### 2.5 Why ffmpeg is optional

`ffmpeg.exe` is 80 MB to 160 MB and serves only the RTSP publisher. Recording
does not need it, because `oak_bridge.py` writes clips through
`cv2.VideoWriter` with the `mp4v` codec.

Making it optional keeps a build without RTSP roughly 150 MB smaller. The RTSP
thread logs a warning and exits when the binary is absent.

---

## 3. Bugs fixed, with evidence

### 3.1 RTSP failed on every port except 8765

`docker/mediamtx.yml` hardcoded `rtspAddress: :8765`. `oak_bridge.py` built its
publish target from the `mjpeg_port` option.

At the default both read 8765 and the stream worked. At any other value ffmpeg
published to the configured port while mediamtx listened on 8765, and the stream
produced no picture with no error naming the cause.

`oak_launcher.write_mediamtx_config` now generates the file from the same value,
and `docker/mediamtx.yml` is deleted. A release check asserts that
`rtspAddress` tracks the requested port.

### 3.2 Restart was a one-way stop outside Home Assistant

The `/api/restart` handler called `os.kill(os.getpid(), signal.SIGTERM)` and
relied on the S6 supervisor in the Home Assistant base image to start the
process again.

Windows has no `SIGTERM`, and a portable build has no supervisor. The Restart
button would have stopped the program with no way back except starting it by
hand.

`oak_runtime.restart_process` now re-executes. On POSIX it calls `os.execve`.
On Windows it spawns a detached copy and exits, because `os.execv` on Windows
re-quotes arguments and mangles paths holding spaces. The replacement process
waits up to 20 s for the instance marker port, so the two never overlap.

### 3.3 A restart wrote a traceback to the log

`shutdown_children` sets `ffmpeg_proc` to `None` while `rtsp_thread` is still in
its loop. The next iteration called `None.poll` and wrote an `AttributeError`
traceback.

In a windowed build the log is the only diagnostic, so a normal restart read as
a crash. `rtsp_thread` now watches the shutdown event and reads the handle once
per iteration.

---

## 4. Release checks

`python tests/test_modules.py` — 45 checks, 0 failures, run 2026-10-02.

| Group | Checks | Covers |
|---|---|---|
| `oak_paths` | 10 | Override precedence, folder creation, mode detection, fallback when a target rejects writes |
| `oak_logging` | 6 | File creation, message delivery, the `None` stdout shim |
| `oak_runtime` | 9 | Instance lock take, refuse and reuse; binary resolution order; restart wait |
| `oak_launcher` | 14 | Config source precedence, boolean rendering, environment override, generated mediamtx config |
| `oak_tray` | 4 | Import without pystray at module load, autostart target quoting, icon render |
| Icon | 2 | The `.ico` exists and carries the 16 px and 256 px sizes |

Also run and passing:

- `python -m compileall src tools tests` — every file compiles.
- YAML parse of `repository.yaml`, `addon/oak_camera/config.yaml`,
  `windows/oak_config.yaml` and `.github/workflows/release.yml`.
- Add-on manifest version equals the intended tag.
- Root and add-on changelogs are identical.
- Changelog structure: 36 sections, 36 distinct, descending order.
- `python tests/privacy_scan.py` — 27 tracked text files, 0 findings. It
  checks for an email address, a Windows user folder, a MAC address, a device
  serial and an IPv4 literal outside the allowed set.

Every check above runs in the `check` job of the release workflow, so a tag
push cannot build a package that fails one.

---

## 5. Not tested

Name every gap, because none of these ran.

| Not tested | Reason |
|---|---|
| `oak_bridge.py` at runtime | depthai is not installed on the build machine. The file compiles but was never imported. |
| The camera pipeline end to end | No OAK-D LR camera attached. |
| The Windows executable | PyInstaller never ran. Bundle size and startup time in section 6 are estimates, not measurements. |
| The container image | Docker is not installed on the build machine. The Dockerfile is unbuilt. |
| The multi-architecture manifest | Needs the image build. |
| The Home Assistant add-on install | Needs the image published and a Supervisor instance. |
| `cv2.VideoWriter` inside a bundle | Needs the PyInstaller build. See the risk in section 7. |
| The tray icon | pystray is not installed on the build machine. Only the import path and the artwork were checked. |
| The Windows Firewall prompt behaviour | Needs a clean Windows machine. |
| The restart handover | Needs a running process on each platform. |
| The release workflow | Never run. No tag has been pushed. |

The CI smoke test in `.github/workflows/release.yml` closes the third, seventh
and eighth gaps on the first tag push. It starts the executable, waits 75 s, and
asserts that the log reports portable mode, that logging started, that mediamtx
was staged, and that no traceback appeared.

---

## 6. Estimates, not measurements

| Item | Estimate |
|---|---|
| Bundle without ffmpeg | 180 MB to 250 MB |
| Bundle with ffmpeg | 300 MB to 400 MB |
| Onefile startup on a solid state drive | 3 s to 10 s |
| First arm64 image build under emulation | 20 min to 40 min |
| Later image builds with the cache | Much shorter, unmeasured |

Replace each row with a measurement after the first build.

---

## 7. Open risks

### 7.1 Commit metadata carries a real first name, and it is already public

Every commit in this repository is authored under a real first name and an
email address on a personal domain. Both sit in published repository metadata,
which the privacy rule forbids. The values are not repeated here, because this
file is published too. Run the scanner to see them.

9 commits already carry that identity on the remote, pushed 2026-09-30.

This was not fixed in 3.0.0, for two reasons. Changing `git config user.name`
and `user.email` sets the owner's identity, which is the owner's decision. And
correcting the existing commits needs a history rewrite and a force push, which
the Git rule allows only on an explicit order in the same message.

To fix it going forward:

```bash
git config user.name CrystalHeeler
git config user.email <an address you are willing to publish>
```

To correct the published history, order the rewrite. Back up the repository
outside its folder first, as the Git rule requires.

`python tests/privacy_scan.py` reports this on every run and in continuous
integration. It warns and does not fail, because a permanent failure would
block every build until the history is rewritten.

### 7.2 Other risks

1. **`cv2.VideoWriter` needs `opencv_videoio_ffmpeg*.dll` inside the bundle.**
   Some PyInstaller versions miss it. The failure is quiet: `oak_bridge.py` logs
   `VideoWriter failed` and recording stops while everything else runs. The spec
   calls `collect_dynamic_libs("cv2")` to force it. Record a motion clip on a
   clean Windows machine before trusting the build.
2. **The build is not signed.** SmartScreen warns on first run. Only a code
   signing certificate removes it, at roughly 200 to 400 US dollars a year for
   an organisation validated certificate. An unsigned installer would warn the
   same way, so the portable form costs nothing here.
3. **A new container image is private.** Set the package to public after the
   first push or the Supervisor cannot pull it.
4. **depthai v3 wheels come from the Luxonis snapshot index, not PyPI.** Every
   install needs the extra index URL. Confirm a wheel exists for the chosen
   Python version before pinning it.
5. **The add-on folder moved.** Anyone who installed from this repository
   before 3.0.0 must install again.

---

## 8. Version decision

2.5.0 was wrong. The Versioning rule forbids inferring a version from earlier
context, and the number came from context, not from the owner.

3.0.0 is set by the owner. It is also the honest signal, because the install
mechanism changed: the add-on moved folder and switched from a local build to a
prebuilt image.

A separate finding: the changelog held `2.3.10`. The Versioning rule allows one
digit per position, so `2.3.9` is followed by `2.4.0`. The heading moved to its
correct numeric position and the number stayed as shipped, because renaming a
released version falsifies the record.

---

## 9. Release state

Steps 1 to 3 of the release sequence are done: checks run, changelog written,
work committed.

Steps 4 to 6 are not started. No tag exists, no package was built, nothing was
pushed, and no Release was published. The workflow now stages a draft Release,
so a tag push cannot publish on its own.
