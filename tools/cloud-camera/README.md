# camview (prototype)

View Anycubic **cloud** printer cameras on Linux. Upstream disables cloud video on
Linux because the system WebKitGTK has no WebRTC (see
`../../docs/cloud-video-investigation.md`). camview works around that without
modifying any vendor binary:

1. It extracts the Workbench web UI from `lib/libWorkbench.so` and patches the copy:
   the Linux gate is removed and the cloud "play" path hands the Agora (Shengwang)
   session returned by `sendOrder` to a local helper.
2. It starts the slicer with `ACNEXT_WORKBENCH_ENV_VAR` pointing at the patched copy
   (the slicer provides login and signed API requests).
3. The helper opens a viewer in a browser (Chromium family preferred, as a small
   app-style window; Firefox as a fallback, as an ordinary browser window), which
   joins the Agora channel with the Agora Web SDK (same version and settings as the
   slicer).

## Usage

```bash
cd tools/cloud-camera
uv run camview run --appimage ~/AppImages/anycubicslicer.appimage
```

Open the Workbench, select a **cloud** printer and press play **once**. A viewer window
opens. (Pressing play repeatedly makes overlapping joins fail with `UID_CONFLICT`.)

Requirements: `uv`, a browser (tried in this order: the Flatpak `org.chromium.Chromium`,
`chromium`, `google-chrome`, `brave-browser`, the Flatpak `org.mozilla.firefox`,
`firefox`; or set `CAMVIEW_BROWSER` to a command, where Firefox-based browsers are
recognised by the executable name or Flatpak app id: `firefox*`, `librewolf`, `zen`,
`waterfox`, `floorp`, `icecat`; everything else gets Chromium arguments), network
access to download the Agora Web SDK once (cached in `~/.cache/camview`, SHA-256
verified).

`uv run camview prepare --appimage PATH OUT_DIR` writes the patched web UI to a
directory for inspection.

### Inside the camview AppImage

The `-camview` AppImage releases ship this tool (without `uv`). Run it with the host
`python3` (3.11 or newer) and no `--appimage` argument:

```bash
./AnycubicSlicer-camview-x86_64.AppImage camview run
```

Any other arguments start the slicer as usual.

## Security notes

- The helper listens on `127.0.0.1` only; every request needs a random per-run token,
  and the `Host` header is checked.
- The viewer window is opened with a one-time ticket, not the token, because other
  local users can read a browser's command line. Reloading the viewer window
  therefore shows 403; close it and press play again.
- The session contains temporary Agora credentials. They are held in memory for two
  minutes and never logged or written to disk.
- Do not paste logs that contain tokens or session data.

## Limitations

- Only printers that return a Shengwang/Agora session (not AWS-only) are supported.
- The slicer UI keeps showing "connecting" after the hand-off; the video is in the
  viewer window.
- It depends on undocumented behaviour and breaks if Anycubic changes the web UI;
  patch failures abort with a clear message instead of running a half-patched UI.
- Agora encryption in the browser is untested on Firefox. The stream is H.264, which
  Firefox may only play with its OpenH264 plugin enabled (`about:addons`, Plugins).
  Firefox also keeps the viewer URL in its history and session restore; its one-time
  ticket is used up by then, so a restored tab shows 403.
- The viewer window closes itself when the slicer exits (tested with the Chromium
  and Firefox Flatpaks; a browser that refuses says so in the window). If the helper is unreachable for another reason, the
  viewer keeps retrying and leaves the channel after about a minute.
