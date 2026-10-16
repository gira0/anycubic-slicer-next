# Cloud-connected video monitoring on Linux

Investigation into enabling cloud-connected video monitoring in the Linux
AppImage and Flatpak. **Outcome: not achievable inside the packaged app as it
stands, and no vendor binary is patched. A separate viewer works as a
workaround; see "Working workaround" below.** Read this before trying again. Project rules are in
`AGENTS.md`.

## Problem

For cloud-connected printers the Workbench video slot shows:

> Video monitoring is currently limited to LAN mode. Cloud-connected video will
> be supported in future versions

Upstream never fixed this on Linux, although Windows and macOS play cloud video.

## Findings

Investigated by decompiling the Anycubic Android app
(`Anycubic_1.1.27_APKPure.apk`, 150 MB, git-ignored; never commit it) and by
unpacking the slicer's `lib/libWorkbench.so`. Version tested: slicer 2.0.0.5.

### Where the video code lives

The Workbench is a Vue web app shown in a wxWebView (WebKitGTK). It is not
remote: it is a zip archive embedded in `lib/libWorkbench.so` (about 39 MB, 288
entries, mostly deflated). Find it from the last `PK\x05\x06` record:
`zip_start = eocd - cd_size - cd_offset`, then open `data[zip_start:]` with
`zipfile`. The video slot is `js/src_views_workbench2_WorkbenchV3_vue.js`.

It contains both cloud backends the Android app uses:

| Backend | Slicer code | Android app code |
| --- | --- | --- |
| Shengwang (Agora) RTC | `AgoraConnectionManager`, `agora-rtc-sdk-ng` | `com.anycubic.lib.video.agora.*`, `ShengwangTokenBean` |
| AWS Kinesis Video WebRTC | `WebRTCConnectionManager`, `startAwsStream` | `com.anycubic.lib.video.kvs.*`, `PeerConnectionClient` |

Both use the same REST call. The slicer posts to `/work/operation/sendOrder`
with `{order_id: 1001, printer_id, shengwang_rtc_support}`, and the app calls
`PeerVideoService.sendCommandPeerVideo(order_id, printer_id)`. The cloud then
wakes the printer's camera over MQTT and returns `token` (AWS credentials)
and/or `shengwang` (`appid`, `channel`, `rtc_token`, `client_uid`,
`encryption_*`). LAN video is separate and uses FLV, not WebRTC.

### The Linux gate

One platform check disables it:

```js
function isLinuxCloudCameraUnsupported(printerType, platformIsLinux) {
  return platformIsLinux === true && printerType === 'cloud';
}
```

It drives `linuxCloudCameraUnsupported` in `WorkbenchV3`, which disables the
play button and shows the `video_lan_only` string. Changing `=== true` to
`=== null` removes the gate. That part works (see experiments below).

### The real blocker: no WebRTC in the system WebKitGTK

With the gate removed, play works, `sendOrder` succeeds, and the Agora SDK
starts joining, then fails with:

```
ReferenceError: Can't find variable: RTCPeerConnection
```

The webview has no WebRTC at all. The app does call
`webkit_settings_set_enable_webrtc(TRUE)`, but WebKitGTK only provides WebRTC if
it was built with the GStreamer WebRTC backend (`-DUSE_GSTREAMER_WEBRTC=ON`,
needs `libnice` and `libsrtp`). Both cloud paths (Agora Web SDK and AWS KVS)
need `RTCPeerConnection`, which is almost certainly why upstream disabled it on
Linux.

- Host Fedora 44 WebKitGTK 2.54: no `GStreamerMediaEndpoint` or `webrtcbin`
  symbols, so no WebRTC.
- The AppImage uses the host WebKitGTK, so it cannot fix this.
- GNOME runtimes (checked in `gnome-build-meta`): 48 has WebKitGTK 2.50.6, and
  49/50 have 2.54.1. All use default CMake options with no WebRTC flag and no
  `libnice`/`libsrtp` dependency, so the Flatpak cannot either.
- The only path left is building WebKitGTK ourselves with the WebRTC backend
  (hours-long build, experimental backend, unverified support for what the
  Agora SDK needs such as encrypted media). Not recommended.

## Working workaround: `tools/cloud-camera` (camview)

Verified on slicer 2.0.0.5 with a real cloud printer (Agora/Shengwang session):
cloud video plays in a separate Chromium window. It uses the
`ACNEXT_WORKBENCH_ENV_VAR` override (see below) with a patched copy of the web
UI that removes the Linux gate and hands the `sendOrder` Shengwang session to a
local helper, which opens a viewer page that joins the channel with the Agora Web
SDK (the version the slicer bundles, 4.24.4) in a WebRTC-capable browser. No
vendor binary is modified. See `tools/cloud-camera/README.md`. Limits: Agora
sessions only (not AWS-only printers), and the slicer UI keeps showing
"connecting" after the hand-off.

## Experiments and dead ends

### Patching `libWorkbench.so` crashes the app

The patch itself is easy: recompress the deflated entry (zlib level 9 is about
1.7 KB larger than the original slot, so strip pure-comment webpack banners and
pad the deflate stream with empty blocks to the exact original compressed size;
fix CRC32 and sizes). The resulting archive is valid (`zipfile.testzip()`, JS
parses, only the one entry differs).

**But the app segfaults at startup** (jump to a garbage heap address, before any
app log). Flipping a single bit in an unrelated stored PNG with a corrected CRC
crashes it too, so the app has an integrity check on `libWorkbench.so`. The main
binary links an MD5 helper (`Anycubbic::Encrypt::sha_md5_file`). I did not trace
or defeat the check, and shouldn't: it would mean disabling a vendor integrity
protection. **Do not ship a modified `libWorkbench.so`.**

### `ACNEXT_WORKBENCH_ENV_VAR` works (unmodified binaries)

The main binary does `getenv("ACNEXT_WORKBENCH_ENV_VAR")` and uses the value as
the Workbench page URL. Otherwise it uses `<scheme>://<host>/Workbench/index.html`.
Verified: extract the archive to a folder and launch the unmodified app with

```bash
ACNEXT_WORKBENCH_ENV_VAR=file:///path/to/extracted/index.html ./AppRun
```

The local UI loads, login stays valid, printers list and the API calls work (the
`anycubic://localhost/api/v1/account/headers` native scheme is accessible from a
`file://` origin). This is the clean way to apply a web-layer patch without
touching vendor binaries. It is only useful once WebRTC exists in the webview.

### Debugging tips for the local-override setup

- Report errors from the page: inject a hook into `index.html` that sends
  `console.warn/error`, `window.onerror`, `unhandledrejection` and XHR statuses to
  a local HTTP server via `new Image().src = 'http://127.0.0.1:PORT/...'`.
  **Redact long token-like strings and never log API response bodies**: the
  `sendOrder` response contains temporary AWS/Agora credentials.
- `UID_CONFLICT` from Agora appears when `play`/retry is clicked repeatedly:
  several overlapping joins use the same `client_uid`. Click once and wait.
- Do not use `pkill -f` or `pgrep -f` with patterns that appear in your own
  command line; match the process name instead (`pgrep -x AnycubicSlicerN`).
- The app's data dir and logs are under `~/.config/AnycubicSlicerNext/` and
  `~/.AnycubicSlicerNext/`.

## If you revisit this

1. Check whether the target WebKitGTK now has WebRTC: in the running page,
   `typeof RTCPeerConnection` must not be `"undefined"`. Newer runtimes or a
   distro build with `USE_GSTREAMER_WEBRTC` would change the picture.
2. If it does, test with the env-var override first (extract, change `=== true`
   to `=== null` in `isLinuxCloudCameraUnsupported`, launch with
   `ACNEXT_WORKBENCH_ENV_VAR`). If cloud video plays, package it by shipping the
   patched web folder in the AppImage and exporting the variable in `AppRun`.
   Do not modify `libWorkbench.so`.
3. Check the Android app (`PeerVideoService`, `AgoraConnectionClient`,
   `PeerConnectionClient`) as the reference for the expected signalling flow.
4. Treat temporary credentials from the cloud API as secrets. Do not log or commit
   them.
