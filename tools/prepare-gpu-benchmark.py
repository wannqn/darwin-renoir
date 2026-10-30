#!/usr/bin/env python3
"""Prepare RAM-only GPU comparison payloads; does not contact the phone."""
import argparse
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = struct.Struct("<16sII")
WORKLOAD = b"""# Repeatable unlock, open Settings, scroll, return home, and repeat.
/redwood/bin/rwtouch wait 35 swipe 0.5 0.985 0.5 0.3 250 wait 4 tap 0.85 0.70 wait 4 swipe 0.5 0.80 0.5 0.30 250 wait 1 swipe 0.5 0.30 0.5 0.80 250 wait 2 swipe 0.5 0.985 0.5 0.25 250 wait 4 tap 0.85 0.70 wait 4 swipe 0.5 0.80 0.5 0.30 250 wait 1 swipe 0.5 0.30 0.5 0.80 250 wait 2 swipe 0.5 0.985 0.5 0.25 250
"""

def checked_workload(path):
    import sys
    sys.path.insert(0, str(ROOT / 'tools/apfs'))
    import apfs
    container = apfs.Container(str(path))
    try:
        volume = apfs.pick_volume(container, None)
        hit = volume.lookup('/etc/rc.jobs')
        if hit is None or volume.inode(hit[0]).contents() != WORKLOAD:
            raise ValueError('Build SHARE=1 GL=1 RC_JOBS=rc.jobs.gpu-benchmark userland/build.sh first')
    finally:
        container.close()
    return path.read_bytes()

def make_payload(raw, kernel, speed, ramdisk):
    magic, size = struct.unpack_from("<II", raw)
    if magic != 0x50554e58 or size != len(raw)-8:
        raise ValueError("Invalid XNUP")
    offset, result, seen = 8, [], set()
    while offset + ENTRY.size <= len(raw):
        name, size, reserved = ENTRY.unpack_from(raw, offset)
        offset += ENTRY.size
        key = name.rstrip(b"\0")
        if not key:
            if size or reserved or offset != len(raw):
                raise ValueError("Invalid terminator")
            break
        if key in seen or offset + ((size + 15) & ~15) > len(raw):
            raise ValueError("Invalid entry")
        seen.add(key)
        body = raw[offset:offset+size]
        offset += (size+15) & ~15
        if key == b"kernel": body = kernel
        if key == b"ramdisk": body = ramdisk
        if key == b"cmdline":
            words = body.rstrip(b"\0").decode().split()
            words = [x for x in words if not x.startswith(("adreno_speed=", "touch_lat=", "loader_return_after="))]
            body = (" ".join(words + [f"adreno_speed={speed}", "touch_lat=1", "loader_return_after=110"])).encode() + b"\0"
        result.append(ENTRY.pack(name, len(body), reserved) + body + b"\0" * (-len(body) % 16))
    else: raise ValueError("Missing terminator")
    if not {b"kernel", b"ramdisk", b"cmdline"} <= seen:
        raise ValueError("Missing required entry")
    data = b"".join(result) + b"\0" * ENTRY.size
    return struct.pack("<II", 0x50554e58, len(data)) + data

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="existing XNUP payload")
    ap.add_argument("kernel", type=Path, help="rebuilt Renoir kernel")
    ap.add_argument("output_dir", type=Path, help="directory for test payloads")
    ap.add_argument("--ramdisk", type=Path, default=ROOT / "userland/root.apfs",
                    help="APFS built with RC_JOBS=rc.jobs.gpu-benchmark and SHARE=1")
    args = ap.parse_args()
    ramdisk = checked_workload(args.ramdisk)
    raw, kernel = args.input.read_bytes(), args.kernel.read_bytes()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for speed in (1, 2):
        out = args.output_dir / f"gpu-benchmark-{speed}.bin"
        out.write_bytes(make_payload(raw, kernel, speed, ramdisk))
        print(f"{out}: {out.stat().st_size} bytes")

if __name__ == "__main__": main()
