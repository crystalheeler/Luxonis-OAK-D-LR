OAK-D LR Camera — portable build for Windows
=============================================

WHAT THIS IS
  A standalone version of the Luxonis OAK-D LR camera bridge. It runs the same
  AI detection, RTSP stream, motion recording and web settings page as the
  Home Assistant add-on. It needs no installer and no administrator rights.

FIRST RUN
  1 Unzip this folder anywhere you can write to. A USB stick works.
    Do not use C:\Program Files: Windows blocks writes there, and the program
    then falls back to %LOCALAPPDATA%\OakCamera for its data.
  2 Open oak_config.yaml in a text editor. Set camera_ip to the address of
    your OAK-D LR. Save the file.
  3 Run OakCamera.exe.
  4 Windows Firewall asks to allow the program. Click Allow for private
    networks. You are asked once for OakCamera.exe and once for mediamtx.exe.
    Decline, and the stream works on this computer only.
  5 A camera icon appears in the notification area, next to the clock.
    Right-click it and choose Open settings.

THE TRAY ICON
  Open settings            the web panel, at http://localhost:8767/
  View log                 opens oak_camera.log
  Open data folder         settings, the log and the generated mediamtx config
  Open recordings folder   the motion clips
  Start with Windows       adds or removes a startup entry for your account
  Restart                  reloads the camera pipeline
  Quit                     stops the program and every child process

WHERE THINGS GO
  data\oak_settings.json   per-object detection settings from the web panel
  data\oak_camera.log      rotating log, 2 MB per file, 5 files
  recordings\              motion clips, named motion_<time>_<objects>.mp4
  models\                  put yolo11n.tar.xz here to use the yolo11n model
  bin\                     mediamtx.exe and ffmpeg.exe, copied on first run

  All of these sit beside OakCamera.exe, so the whole folder is portable.
  Point them somewhere else with recordings_dir, data_dir and models_dir in
  oak_config.yaml.

PORTS
  8765   RTSP stream, at rtsp://<this-pc>:8765/stream
  8766   JPEG snapshot, at http://<this-pc>:8766/snapshot
  8767   settings page and the live MJPEG feed
  8764   held open internally to stop a second copy from starting

UPGRADING
  Unzip the new version over this folder and keep your data, recordings and
  models folders. Your oak_config.yaml is not overwritten.

HOME ASSISTANT
  Leave ha_token empty and the program runs fully standalone.
  Fill in ha_url and a long-lived access token to send motion events, storage
  alerts and a storage sensor to Home Assistant.

TROUBLESHOOTING
  Nothing happens          read data\oak_camera.log. The program is windowed,
                           so it reports every error there and never opens a
                           console.
  No camera found          check camera_ip, and ping the camera.
  No RTSP stream           ffmpeg.exe or mediamtx.exe is missing, or you denied
                           the firewall prompt. The log names the cause. The
                           MJPEG feed and recording still work without them.
  Already running          another copy holds port 8764. Quit it from the tray
                           icon, or end OakCamera.exe in Task Manager.
  SmartScreen warning      this build is not code-signed. Choose More info,
                           then Run anyway.

SOURCE AND ISSUES
  https://github.com/crystalheeler/Luxonis-OAK-D-LR
