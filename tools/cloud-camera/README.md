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
3. The helper opens a small viewer in a Chromium-family browser, which joins the
   Agora channel with the Agora Web SDK (same version and settings as the slicer).

## Usage

```bash
cd tools/cloud-camera
uv run camview run --appimage ~/AppImages/anycubicslicer.appimage
```

Open the Workbench, select a **cloud** printer and press play **once**. A viewer window
opens. (Pressing play repeatedly makes overlapping joins fail with `UID_CONFLICT`.)

Requirements: `uv`, a browser: Chromium family (Flatpak `org.chromium.Chromium`,
`chromium`, `google-chrome`, `brave-browser`; preferred, opens an app-style window) or
Firefox (Flatpak `org.mozilla.firefox` or `firefox`; opens a normal window); or set
`CAMVIEW_BROWSER`, network
access to download the Agora Web SDK once (cached in `~/.cache/camview`, SHA-256
verified).

`uv run camview prepare --appimage PATH OUT_DIR` writes the patched web UI to a
directory for inspection.

## In the AppImage

The AppImage built by `appimage/build-latest.sh` bundles this package under
`share/camview` and `AppRun` starts it automatically (`camview sidecar`):

- It runs with the host `python3` (3.9 or newer, stdlib only) before `AppRun` exports the
  bundled library path, so Python and the browser never see the bundled libraries.
- It patches the web UI **on the user's machine** from the installed `libWorkbench.so`
  and caches the result in `~/.cache/camview/webui/`, keyed by the library's hash and the
  patch version. Patched copies of Anycubic's web assets are never shipped in releases.
- It passes the helper port and token in the URL (`?cv=PORT.TOKEN`; the slicer appends its
  own query after it). It exits when the slicer exits.
- If anything is missing (no `python3`, no supported browser, the patch no longer
  matches the installed slicer) nothing is written and the stock slicer starts. The build
  prints a `::warning::` when the patch no longer applies to a new slicer version.
- Disable with `ANYCUBIC_CLOUD_CAMERA=0`. Set `CAMVIEW_BROWSER` to choose the browser
  command (for example `flatpak run org.chromium.Chromium`).

## Security notes

- The helper listens on `127.0.0.1` only; every request needs a random per-run token,
  and the `Host` header is checked.
- The session contains temporary Agora credentials. They are held in memory for two
  minutes and never logged or written to disk.
- Do not paste logs that contain tokens or session data.

## Limitations

- Only printers that return a Shengwang/Agora session (not AWS-only) are supported.
- The slicer UI keeps showing "connecting" after the hand-off; the video is in the
  viewer window.
- It depends on undocumented behaviour and breaks if Anycubic changes the web UI;
  patch failures abort with a clear message instead of running a half-patched UI.
- Firefox is verified with the Flatpak on Kobra S1 (including Agora encryption); a
  natively installed `firefox` should behave the same but is untested.
