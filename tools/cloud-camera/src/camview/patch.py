"""Extract the Workbench web UI from libWorkbench.so and patch it.

The web UI is a zip archive embedded in libWorkbench.so. We never modify
libWorkbench.so (the slicer crashes on any change to it); instead the patched
copy is loaded through the ACNEXT_WORKBENCH_ENV_VAR URL override.
"""
import io
import re
import struct
import zipfile
from pathlib import Path

GATE = "return platformIsLinux === true && printerType === 'cloud';"
GATE_OFF = "return platformIsLinux === null && printerType === 'cloud';"
VIDEO_JS = "js/src_views_workbench2_WorkbenchV3_vue.js"


class PatchError(RuntimeError):
    pass


def extract_webui(lib: Path, dest: Path) -> None:
    """Extract the zip archive embedded in libWorkbench.so into dest."""
    data = lib.read_bytes()
    eocd = data.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise PatchError(f"no embedded zip archive found in {lib}")
    _, cd_size, cd_off = struct.unpack_from("<10xHII", data, eocd)
    zip_start = eocd - cd_size - cd_off
    with zipfile.ZipFile(io.BytesIO(data[zip_start:])) as z:
        z.extractall(dest)


def _replace_once(text: str, old: str, new: str, what: str) -> str:
    if text.count(old) != 1:
        raise PatchError(
            f"cannot patch {what}: expected 1 match, found {text.count(old)} "
            "(the slicer web UI changed; see docs/cloud-video-investigation.md)"
        )
    return text.replace(old, new)


HANDOFF = """async startShengwangStream(printer) {
      const __cv = window.__CAMVIEW;
      const res = await (0,%(mod)s.getAwsToken)({
        order_id: 1001,
        printer_id: printer.id,
        shengwang_rtc_support: true
      });
      const sw = res && res.data && res.data.shengwang;
      if (!res || res.code !== 1 || !sw || !sw.appid || !sw.channel) {
        throw new Error((res && res.msg) || 'camview: no Shengwang session in the sendOrder response');
      }
      const r = await fetch(__cv.url + '/session', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Camview-Token': __cv.token},
        body: JSON.stringify({printer: {id: printer.id, name: printer.name || printer.printer_name || ''}, shengwang: sw})
      });
      if (!r.ok) throw new Error('camview helper rejected the session: ' + r.status);
      this.isConnecting = false;
      this.isPlaying = false;
      this.tipsNum = 1;
    },
    async startShengwangStreamUnused(printer) {"""


def patch_webui(root: Path, helper_url: str, token: str) -> None:
    video = root / VIDEO_JS
    if not video.exists():
        raise PatchError(f"{VIDEO_JS} not found in the extracted web UI")
    js = video.read_text(encoding="utf-8")

    # 1. Remove the Linux gate so the play button works for cloud printers.
    js = _replace_once(js, GATE, GATE_OFF, "the Linux cloud camera gate")

    # 2. Always use the Shengwang (Agora) path; AWS-only printers are unsupported.
    js = _replace_once(js, "if (this.shengwangRdtSupport) {", "if (true) {", "the Shengwang path selection")

    # 3. Hand the Shengwang session to the local helper instead of joining in-page
    #    (the system WebKitGTK has no WebRTC).
    m = re.search(r"\(0,(_api_network_printer_js__WEBPACK_IMPORTED_MODULE_\d+__)\.getAwsToken\)", js)
    if not m:
        raise PatchError("cannot find the getAwsToken import in the web UI")
    js = _replace_once(
        js,
        "async startShengwangStream(printer) {",
        HANDOFF % {"mod": m.group(1)},
        "startShengwangStream",
    )
    video.write_text(js, encoding="utf-8")

    # 4. Tell the page where the helper is (and mark the override visibly).
    index = root / "index.html"
    html = index.read_text(encoding="utf-8")
    cfg = f'<script>window.__CAMVIEW={{url:"{helper_url}",token:"{token}"}};</script>'
    html = _replace_once(html, "<head>", "<head>" + cfg, "index.html <head>")
    index.write_text(html, encoding="utf-8")
