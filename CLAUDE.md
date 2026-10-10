# CLAUDE.md

Read `AGENTS.md` first for project scope, AppImage automation, validation and
release-safety rules. This file records the cloud video investigation and patch.

## Cloud video patch (AppImage)

### Problem

For cloud-connected printers the Workbench video slot shows:

> Video monitoring is currently limited to LAN mode. Cloud-connected video will
> be supported in future versions

Upstream never fixed this on Linux, although Windows and macOS play cloud video.

### Findings

Investigated by decompiling the Anycubic Android app
(`Anycubic_1.1.27_APKPure.apk`, untracked and 150 MB; never commit it) and by
unpacking the slicer's `lib/libWorkbench.so`.

**The slicer already contains working cloud video.** The Workbench is a Vue web
app shown in a wxWebView (WebKitGTK). It is not remote: it is a zip archive
embedded in `lib/libWorkbench.so`, at the offset found from the zip
end-of-central-directory record (about 39 MB, 288 entries). The video slot is
`js/src_views_workbench2_WorkbenchV3_vue.js` in that archive. It bundles both
cloud backends the Android app uses:

| Backend | Slicer code | Android app code |
| --- | --- | --- |
| Shengwang (Agora) RTC | `AgoraConnectionManager`, `agora-rtc-sdk-ng` | `com.anycubic.lib.video.agora.*`, `ShengwangTokenBean` |
| AWS Kinesis Video WebRTC | `WebRTCConnectionManager`, `startAwsStream` | `com.anycubic.lib.video.kvs.*`, `PeerConnectionClient` |

Both clients use the same REST call: the slicer posts to
`/work/operation/sendOrder` with `{order_id: 1001, printer_id, shengwang_rtc_support}`,
and the app calls `PeerVideoService.sendCommandPeerVideo(order_id, printer_id)`.
The call makes the cloud wake the printer's camera over MQTT. The response
holds `token` (AWS `region`, `sessionToken`, `tmpSecretId`, `tmpSecretKey`)
and/or `shengwang` (`appid`, `channel`, `rtc_token`, `client_uid`,
`encryption_mode/key/kdf_salt`). The app picks Shengwang when the printer
supports it and falls back to AWS. The slicer's flow matches this.
LAN video is separate and uses `webrtcstreamer.js`.

**The only blocker is one platform check** in the `cameraSupport` module:

```js
function isLinuxCloudCameraUnsupported(printerType, platformIsLinux) {
  return platformIsLinux === true && printerType === 'cloud';
}
```

It drives `linuxCloudCameraUnsupported` in `WorkbenchV3`, which disables the
play button and shows the `video_lan_only` i18n string above. It is the only
use of `isLinux()` in the camera path. The Chinese comment says it was aligned
with the old workbench and `shengwangDoc`, so it was probably disabled on Linux
for the old Agora SDK. WebKitGTK exposes `enable-webrtc`, and the LAN video
already needs WebRTC in the same webview, so there is no obvious technical
reason for the restriction.

### The patch

`appimage/patch-cloud-video.py` is run by `appimage/build-latest.sh` only when
`VARIANT=cloud-video` (the stable build is never patched), right after the
Debian contents are copied in, with `--strict` so a vanished pattern fails the
build instead of publishing an unpatched "patched" AppImage. It changes `platformIsLinux === true`
to `=== null` in the embedded zip entry.

The entry is deflate-compressed and the archive sits at a fixed size inside the
ELF, so the script does not rewrite the file:

1. It recompresses the patched JS (zlib level 9). That is about 1.7 KB larger
   than the original slot, so it strips the minimum number of pure-comment
   webpack banners (`/*!****!*\ ... \****/`) found by binary search.
2. It pads the deflate stream with empty deflate blocks to exactly the original
   compressed size, so no offsets move.
3. It updates the CRC32 and uncompressed size in the local and central headers.
4. It self-checks by inflating the rebuilt stream.

It is idempotent. If the pattern is missing (upstream changed or fixed it),
behaviour depends on the mode:

- Without `--strict` (manual use): it prints a `::warning::` and leaves the file
  alone with exit 0.
- With `--strict` (what `build-latest.sh` uses for `VARIANT=cloud-video`, so the
  CI release path): it exits 1, the `cloud-video` job fails, and the existing
  pre-release is left as it was. The stable release job is a separate job and is
  not affected.

If the new entry cannot fit in the original slot, it exits 1 in both modes.

Verified on the 2.0.0.5 `libWorkbench.so`:

- the file size is unchanged;
- `zipfile.testzip()` passes on every entry;
- only `WorkbenchV3_vue.js` differs;
- its contents equal the original plus the one-token change minus 218 banner
  comments;
- `node --check` parses the result.

**Not verified end to end.** It has not been tested against a real
cloud-connected printer with a logged-in account. After changing the patch or
bumping the slicer version, test in the AppImage: log in, select a cloud
printer, press play, and check that the video shows instead of the LAN-only
text.

### Release pipeline

`.github/workflows/appimage.yml` publishes two things per application version:

- the stable release `<version>` (unpatched, unchanged behaviour), and
- a **rolling pre-release tagged `cloud-video`** with the patched AppImage:
  `AnycubicSlicer-<version>-cloud-video-x86_64.AppImage`,
  `AnycubicSlicer-cloud-video-x86_64.AppImage` and its `.zsync`. Old versioned
  patched assets are deleted; the release title carries the current version and
  the `cloud-video` tag is moved to the commit that built the assets.

The patched AppImage embeds `gh-releases-zsync|...|cloud-video|...` update
information, because the `latest` tag skips pre-releases. The `check` job
checks both releases separately, so the expensive builds are skipped when each
is complete. Never publish the patched build as a normal release.

### If it stops working

- **"pattern not found" (a warning locally, a failed `cloud-video` job in CI).**
  Upstream changed the function. Re-extract the archive (steps below) and look at
  `isLinuxCloudCameraUnsupported` / `linuxCloudCameraUnsupported` again.
  Upstream may have enabled Linux, which means the patch can be removed.
- **Play button works but no video.** Check the WebKit console. Likely causes
  are missing H.264 or GStreamer codecs on the host
  (`gstreamer1.0-plugins-bad`, `gstreamer1.0-libav`), WebKitGTK built without
  WebRTC, or the Agora Web SDK's browser-support check. The Android app is the
  reference for the expected signaling flow.
- **Reading the web code.** Extract the archive: find the last `PK\x05\x06`
  record in `libWorkbench.so`, compute `zip_start = eocd - cd_size - cd_offset`,
  and open `data[zip_start:]` with `zipfile`.

### Other leads and non-goals

- `ACNEXT_WORKBENCH_ENV_VAR`: the main binary does `getenv()` on this to get the
  Workbench URL. If unset, it builds `<scheme>://<host>/Workbench/index.html`.
  It looks like a full-URL override, which could load an unpacked patched
  Workbench without touching the library. This is untested. On Linux the page
  calls `fetch('anycubic://localhost/api/v1/account/headers')`, a native custom
  scheme, so a different origin may be blocked by CORS.
- The Flatpak (`flatpak/com.anycubic.AnycubicSlicer.yml`) is not patched. The
  same script can be applied to `/app/lib/libWorkbench.so` if wanted.
- Do not try to reimplement the video protocols natively. The slicer's own web
  code already does this.
- Treat the temporary AWS/Agora credentials returned by the cloud API as
  secrets. Do not log them or commit captured responses.

## Validation

Run the checks from `AGENTS.md`, plus:

```bash
python3 -I -m py_compile appimage/patch-cloud-video.py
```

To test the patch without building, copy a `libWorkbench.so` out of an
extracted AppImage or `.deb`, run the script on the copy twice (the second run
must print "already applied"), then confirm with `zipfile.testzip()` and
`node --check` on the extracted `WorkbenchV3_vue.js`.
