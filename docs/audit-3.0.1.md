# Audit note — 3.0.1

Companion to the 3.0.1 changelog entry. 3.0.0 shipped two defects that only a
real Windows desktop could show. Both came from the same decision: a windowed
executable with no window.

Owner: CrystalHeeler. Date: 2026-10-02.

---

## 1. What the report showed

The owner ran `OakCamera.exe` from an unzipped 3.0.0 package. Two black console
windows opened and nothing else appeared.

The log told a different story. Every subsystem started: the config loaded, both
child binaries staged, mediamtx opened its 5 listeners, all 8 threads ran, both
servers bound, and the tray icon started. The program worked. It just could not
show that it did.

---

## 2. Root causes

### 2.1 Two console windows

mediamtx and ffmpeg are console programs. The parent is built with
`console=False`, so it owns no console to share. Windows then gives each child
a console window of its own.

The smoke test in continuous integration could not catch this. A build runner
has no interactive desktop, so a console window costs nothing there and nothing
fails. Only a real desktop shows it.

Fix: both spawn sites pass `CREATE_NO_WINDOW` through
`oak_runtime.child_creation_flags()`. Their output still reaches the log,
because both are started with a pipe.

### 2.2 Nothing visible happened

A windowed build shows no window by design, and Windows files a new tray icon
into the hidden overflow area. The only sign of life was a log file the user
had no reason to open.

Fix: the launcher waits for the settings server to listen, then opens the page.
`open_settings_on_start` turns it off. The add-on never opens it, because Home
Assistant owns that panel.

### 2.3 Shut down did not stop the add-on

The owner pressed Shut down in the Home Assistant panel. The feed stopped, but
the add-on kept holding the camera, which then blocked the Windows build from
connecting.

`request_shutdown` calls `os._exit(0)`. Inside the add-on that exits the
container's main process, and the Supervisor restarts the container. The button
therefore stopped the feed and brought the add-on straight back.

Fix: the button is not rendered inside the add-on, and `/api/shutdown` returns
409 there. Home Assistant's own Stop control is the correct one.

This was a design error, not a coding error. The button was added in 3.0.0 for
a portable Linux run with no tray icon, and it was never reasoned about for the
add-on.

---

## 3. Release checks

`python tests/test_modules.py` — 53 checks, 0 failures.

8 checks are new in 3.0.1:

| Check | Guards |
|---|---|
| `child_creation_flags` is correct per platform | 2.1 |
| ffmpeg spawns with the flag | 2.1, because a helper nobody calls fixes nothing |
| mediamtx spawns with the flag | 2.1 |
| The standalone page offers Shut down | 2.3 |
| The add-on page hides Shut down | 2.3 |
| Hiding it removes exactly one button | 2.3 |
| Every other control survives | 2.3 |
| The production marker port is 8764 | the port change below |

The suite previously bound the live marker port 8764, so it failed on any
machine already running the program. That is the single instance guard working,
not a defect. `acquire_single_instance` now takes a port, the test picks a free
one, and a separate check pins the production value.

---

## 4. Not tested

| Not tested | Reason |
|---|---|
| That no console window appears | Needs an interactive Windows desktop. The build runner has none, which is why 3.0.0 shipped the defect. |
| That the settings page opens | Same reason. The browser call is guarded, so a failure logs and does not stop the program. |
| The camera pipeline end to end | Not yet connected. See section 5. |
| `cv2.VideoWriter` recording | Needs a motion event, which needs a camera. |
| The add-on Stop path | Needs a Supervisor instance. |

Both desktop checks need the owner to run the build. Continuous integration
cannot close them.

---

## 5. The camera

3.0.0 could not reach the camera. The log shows discovery finding a device on
the network and the connection then failing with `X_LINK_DEVICE_NOT_FOUND`.

The likely cause is section 2.3: the add-on still held the camera. An OAK device
serves one host at a time.

The auto-discovery code path was left alone. It calls bare `dai.Device()`, which
is the correct way to find any device, including a USB one. Forcing the TCP/IP
protocol and the bootloader state onto it, as the explicit address path does,
would break USB discovery. Setting `camera_ip` selects the explicit path, which
is the documented route for a Power over Ethernet camera.

Retest in this order:

1. Stop the add-on from Home Assistant, not from the settings page.
2. Set `camera_ip` in `oak_config.yaml` to the camera's address.
3. Run `OakCamera.exe`.

If it still fails with the add-on stopped and an explicit address, the cause is
not contention and the discovery path deserves another look.

---

## 6. Release state

Steps 1 to 5 are done: checks run, changelog written, work committed, tag cut,
package built. Step 6 is split, as the Git rule requires: the push is done and
the Release is staged as a draft until the owner gives a publish order.
