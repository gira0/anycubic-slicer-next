#!/usr/bin/env python3
"""Enable cloud-connected video monitoring in Anycubic Slicer Next on Linux.

The Workbench web UI is a zip archive embedded in lib/libWorkbench.so. Its
WorkbenchV3 chunk already contains complete cloud camera support (Shengwang /
Agora and AWS KVS WebRTC, the same flow as the Android app) but disables it on
Linux with:

    function isLinuxCloudCameraUnsupported(printerType, platformIsLinux) {
      return platformIsLinux === true && printerType === 'cloud';
    }

which produces "Video monitoring is currently limited to LAN mode...".

This script changes `=== true` to `=== null`. The chunk is deflate-compressed
and the archive is embedded at a fixed size, so the entry is recompressed and
must fit in its original slot: webpack banner comments are stripped to make
room and the deflate stream is padded with empty blocks to the exact original
compressed size. No offsets move; the CRC32 and uncompressed size are updated.

Usage: patch-cloud-video.py [--strict] path/to/libWorkbench.so
Exit 0 when patched or already patched. If upstream changed the code so the
pattern is gone, a warning is printed and the file is left untouched (exit 0),
or exit 1 with --strict. Exit 1 on errors.
"""
import re
import struct
import sys
import zlib

ORIGINAL = b"return platformIsLinux === true && printerType === 'cloud';"
PATCHED = b"return platformIsLinux === null && printerType === 'cloud';"

# webpack module banners, e.g.
#   /*!*****!*\
#     !*** ./src/utils/cameraSupport.js ***!
#     \*****/
BANNER = re.compile(rb"/\*!\*+!\*\\\n  !\*\*\* [^\n]*? \*\*\*!\n  \\\*+/\n")

EOCD_SIG = b"PK\x05\x06"
CDIR_SIG = b"PK\x01\x02"
LOCAL_SIG = b"PK\x03\x04"


class Bits:
    """LSB-first bit writer for hand-built deflate blocks."""

    def __init__(self):
        self.out = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value, nbits):
        self.acc |= value << self.n
        self.n += nbits
        while self.n >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.n -= 8

    def align(self):
        if self.n:
            self.put(0, 8 - self.n)


def padding(nbytes):
    """Return deflate blocks (ending with a final block) of exactly nbytes.

    Must follow a byte-aligned point in the stream (after a sync flush).
    """
    for final_stored in (False, True):
        for k in range(0, 5):  # k non-final empty fixed-Huffman blocks (10 bits each)
            b = Bits()
            for _ in range(k):
                b.put(0b010, 3)  # BFINAL=0, BTYPE=01
                b.put(0, 7)      # end-of-block
            if final_stored:
                b.put(0b001, 3)  # BFINAL=1, BTYPE=00
                b.align()
                b.out += b"\x00\x00\xff\xff"
            else:
                b.put(0b011, 3)  # BFINAL=1, BTYPE=01
                b.put(0, 7)
                b.align()
            rest = nbytes - len(b.out)
            if rest >= 0 and rest % 5 == 0:
                # Non-final empty stored blocks are 5 aligned bytes each; they
                # go first, before the unaligned tail.
                return b"\x00\x00\x00\xff\xff" * (rest // 5) + bytes(b.out)
    raise ValueError(f"cannot build {nbytes} bytes of padding")


def rebuild(raw_old, csize):
    """Return (deflate_bytes, new_raw) for the patched entry, exactly csize long."""
    patched_raw = raw_old.replace(ORIGINAL, PATCHED)
    nbanners = len(BANNER.findall(patched_raw))

    def attempt(strip):
        data = BANNER.sub(b"", patched_raw, count=strip) if strip else patched_raw
        c = zlib.compressobj(9, zlib.DEFLATED, -15, 9)
        body = c.compress(data) + c.flush(zlib.Z_SYNC_FLUSH)
        # Padding needs at least 2 bytes for the final block.
        return (data, body) if len(body) + 2 <= csize else None

    # Strip as few banners as possible: binary search the smallest count that fits.
    if attempt(nbanners) is None:
        raise ValueError("patched entry does not fit in the original compressed size")
    lo, hi = 0, nbanners
    while lo < hi:
        mid = (lo + hi) // 2
        if attempt(mid):
            hi = mid
        else:
            lo = mid + 1
    data, body = attempt(lo)
    stream = body + padding(csize - len(body))
    d = zlib.decompressobj(-15)
    check = d.decompress(stream)
    if not d.eof or d.unused_data or check != data:
        raise ValueError("self-check of rebuilt deflate stream failed")
    return stream, data


def main(path, strict=False):
    with open(path, "rb") as f:
        data = bytearray(f.read())

    eocd = data.rfind(EOCD_SIG)
    if eocd < 0:
        print("error: no zip end-of-central-directory record found", file=sys.stderr)
        return 1
    total, cd_size, cd_off = struct.unpack_from("<10xHII", data, eocd)
    # The archive is appended inside the ELF, so offsets are relative to its start.
    zip_start = eocd - cd_size - cd_off

    patched = already = 0
    pos = zip_start + cd_off
    for _ in range(total):
        if data[pos:pos + 4] != CDIR_SIG:
            print("error: corrupt central directory", file=sys.stderr)
            return 1
        (flags, method, _time, _date, _crc, csize, usize, nlen, xlen, clen) = struct.unpack_from(
            "<HHHHIIIHHH", data, pos + 8)
        local_off = struct.unpack_from("<I", data, pos + 42)[0]
        name = bytes(data[pos + 46:pos + 46 + nlen]).decode("utf-8", "replace")
        cd_entry = pos
        pos += 46 + nlen + xlen + clen

        if not name.endswith(".js") or flags & 0x08:
            continue
        lh = zip_start + local_off
        if data[lh:lh + 4] != LOCAL_SIG:
            print(f"error: bad local header for {name}", file=sys.stderr)
            return 1
        lnlen, lxlen = struct.unpack_from("<HH", data, lh + 26)
        body = lh + 30 + lnlen + lxlen
        stored = bytes(data[body:body + csize])
        if method == 0:
            raw = stored
        elif method == 8:
            raw = zlib.decompress(stored, -15)
        else:
            continue

        if PATCHED in raw:
            already += 1
            continue
        if ORIGINAL not in raw:
            continue

        if method == 0:
            new_stream, new_raw = None, raw.replace(ORIGINAL, PATCHED)
            new_stream = new_raw
        else:
            try:
                new_stream, new_raw = rebuild(raw, csize)
            except ValueError as e:
                print(f"error: {name}: {e}", file=sys.stderr)
                return 1
        assert len(new_stream) == csize
        data[body:body + csize] = new_stream
        crc = zlib.crc32(new_raw) & 0xFFFFFFFF
        struct.pack_into("<II", data, lh + 14, crc, csize)
        struct.pack_into("<I", data, lh + 22, len(new_raw))
        struct.pack_into("<I", data, cd_entry + 16, crc)
        struct.pack_into("<I", data, cd_entry + 24, len(new_raw))
        print(f"patched {name} ({usize} -> {len(new_raw)} bytes uncompressed)")
        patched += 1

    if patched:
        with open(path, "wb") as f:
            f.write(data)
        return 0
    if already:
        print("cloud video patch already applied")
        return 0
    print("::warning::cloud video patch pattern not found; upstream may have "
          "changed or fixed isLinuxCloudCameraUnsupported", file=sys.stderr)
    return 1 if strict else 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--strict"]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(args[0], strict="--strict" in sys.argv[1:]))
