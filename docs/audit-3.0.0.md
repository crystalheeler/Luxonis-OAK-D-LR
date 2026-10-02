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

The v3.0.0 build ran on 2026-10-02 and closed most of these. What the smoke
test proved, from the log it captured:

| Now verified | Evidence from the build |
|---|---|
| `oak_bridge.py` imports and runs inside the bundle | It logged its model, FPS, thresholds and all 8 threads |
| depthai loads from the bundle | It reached `Auto-discovering OAK-D LR` and returned `No available devices` |
| The camera retry loop works | 4 discovery attempts at 10 s intervals, no crash |
| The Windows executable builds | 148.9 MB ZIP, built in 3.5 min |
| The tray icon starts | `Tray icon started` on a headless runner |
| mediamtx starts and its output reaches the log | Its RTSP, RTMP, HLS, WebRTC and SRT listeners all logged through the pipe drain |
| ffmpeg starts | `Starting ffmpeg` with the correct publish target |
| Every server binds | Ports 8766 and 8767 both logged |
| The storage monitor works | `Storage: 2.4% used (3.7 GB / 150.0 GB)` |
| Settings load and apply | `11 active objects, hw threshold 0.10` |
| Per-platform folders resolve | Recordings resolved beside the executable |
| The container image builds | Both `linux/amd64` and `linux/arm64`, public on the registry |
| The release workflow | Ran twice. The first attempt failed and is documented in 5.1. |

Still not tested:

| Not tested | Reason |
|---|---|
| The camera pipeline end to end | No OAK-D LR camera attached to the build runner. |
| `cv2.VideoWriter` inside the bundle | Needs a motion event, which needs a camera. The risk in 7.2 stands. |
| The Home Assistant add-on install | Needs a Supervisor instance. The image is published and public. |
| The Windows Firewall prompt behaviour | Needs a clean Windows machine. The build runner has no interactive desktop. |
| The restart handover | Needs a running process and a request to `/api/restart`. |
| The tray menu actions | The icon starts, but no click was sent. |
| Startup time from a double-click | The smoke test backgrounds the process and does not time the first frame. |

### 5.1 The first build failed

The first v3.0.0 tag push failed the Windows job in 0.8 min:

```
ERROR: script 'windows/src/oak_launcher.py' not found
```

PyInstaller resolves the script path in `Analysis()` relative to the spec file's
folder. The `os.path.isfile` checks in the same spec resolve relative to the
working directory. The spec mixed the two, so the binary lookups found their
files from the repository root while `Analysis` looked under `windows/`.

Every path now derives from `SPECPATH`. The release job was skipped on that
run, so nothing was packaged or published from a failing check. The tag was
re-cut on the fix, because 3.0.0 had never published.

---

## 6. Measurements

Taken from the v3.0.0 build on 2026-10-02. The estimates this section carried
before the build are replaced.

| Item | Estimate before | Measured |
|---|---|---|
| ZIP with ffmpeg bundled | 300 MB to 400 MB | **148.9 MB** |
| Windows job, whole build | not estimated | **3.5 min** |
| Multi-architecture image, cold cache | 20 min to 40 min | **8.3 min** |
| Multi-architecture image, warm cache | unmeasured | **0.6 min** |
| Release checks job | not estimated | **0.2 min** |

The ZIP came in at 40% of the lower estimate. The onefile compression and the
`excludes` list in the spec account for the difference.

Still unmeasured: startup time from a double-click, and the extracted size on
disk. The smoke test backgrounds the process, so it times neither.

---

## 7. Open risks

### 7.1 Commit metadata was rewritten (closed)

Every commit was authored under a real first name and an address on a personal
domain. Both sat in repository metadata, which the privacy rule forbids. 9 of
those commits were public on the remote from 2026-09-30.

The owner ordered the rewrite on 2026-10-02. The work done:

| Step | Result |
|---|---|
| Backup outside the repository | A mirror clone and a bundle, both verified as a complete history |
| Identity set | `CrystalHeeler <crystalheeler@keemail.me>`, the only authorized identifiers |
| Commits rewritten | 14 of 14 |
| Tags re-pointed | 9 of 9, all lightweight |
| A second address in `repository.yaml` | Replaced across all 3 commits that held it. It was local and never published. |
| `refs/original` backups removed, reflog expired, objects collected | 0 unreachable objects remain |

Verified after the rewrite: 1 identity in the whole history, 0 matches for the
old name, and 1 email address across every reachable blob, which is the
authorized one.

**One limit.** A force push removes the branch pointer. GitHub may keep the old
commits reachable by their exact hash until it collects them, and a fork or a
cached view can outlive that. Only GitHub Support can purge them on demand. The
alternative is deleting and recreating the repository, which guarantees removal
but drops the repository's own history and settings.

`python tests/privacy_scan.py` now allows exactly two identifiers,
`CrystalHeeler` and `crystalheeler@keemail.me`, and fails on anything else.

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

All 6 steps are done, on the owner's order of 2026-10-02.

| Step | Result |
|---|---|
| 1 Checks and tests | 45 module checks, the privacy scan, the changelog structure check, YAML parse and compile. All passed. |
| 2 Changelog | Written in the three-section format, 28 lines. |
| 3 Commit | 3 commits on main. |
| 4 Tag | `v3.0.0`, annotated, tagged as CrystalHeeler. |
| 5 Build | 148.9 MB ZIP, plus a two-architecture image on the registry. |
| 6 Push and publish | main and 10 tags force pushed. The Release is published. |

The workflow stages a draft, so the publish was a separate manual step, as the
Git rule requires.
