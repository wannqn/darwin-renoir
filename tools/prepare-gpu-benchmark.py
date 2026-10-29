#!/usr/bin/env python3
"""Prepare RAM-only GPU comparison payloads; does not contact the phone."""
import argparse
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADER = struct.Struct("<8sIIQQQQQQ")
NODE = struct.Struct("<IIIIQQIIIIQQ")
ENTRY = struct.Struct("<16sII")
WORKLOAD = b"""# Repeatable unlock, open Settings, scroll, return home, and repeat.
/redwood/bin/rwtouch wait 35 swipe 0.5 0.985 0.5 0.3 250 wait 4 tap 0.85 0.70 wait 4 swipe 0.5 0.80 0.5 0.30 250 wait 1 swipe 0.5 0.30 0.5 0.80 250 wait 2 swipe 0.5 0.985 0.5 0.25 250 wait 4 tap 0.85 0.70 wait 4 swipe 0.5 0.80 0.5 0.30 250 wait 1 swipe 0.5 0.30 0.5 0.80 250 wait 2 swipe 0.5 0.985 0.5 0.25 250
"""

def with_workload(original):
    image = bytearray(original)
    magic, block, count, nodes, strings, strings_size, data, image_size, _ = HEADER.unpack_from(image)
    if magic != b"PACKFS1\0" or image_size != len(image) or block < 4096 or block & (block - 1):
        raise ValueError("Unsupported packfs image")
    table = [NODE.unpack_from(image, nodes + i * NODE.size) for i in range(count)]
    def name(i):
        n = table[i]
        if n[7] + n[8] > strings_size:
            raise ValueError("Invalid filename")
        return bytes(image[strings+n[7]:strings+n[7]+n[8]]).decode()
    def path(i):
        seen = set()
        parts = []
        while i:
            if i in seen or i >= count:
                raise ValueError("Invalid parent")
            seen.add(i)
            parts.append(name(i))
            i = table[i][6]
        return "/".join(reversed(parts))
    matches = [i for i in range(count) if path(i) == "etc/rc.jobs"]
    if len(matches) != 1:
        raise ValueError("Expected exactly one etc/rc.jobs")
    at = (len(image) + block - 1) & ~(block - 1)
    image.extend(b"\0" * (at - len(image)))
    image.extend(WORKLOAD)
    image.extend(b"\0" * ((-len(image)) % block))
    node = nodes + matches[0] * NODE.size
    struct.pack_into("<QQ", image, node + 16, len(WORKLOAD), at)
    struct.pack_into("<Q", image, node + 56, 0)
    struct.pack_into("<Q", image, 48, len(image))
    return bytes(image)

def make_payload(raw, kernel, speed):
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
        if key == b"ramdisk": body = with_workload(body)
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
    args = ap.parse_args()
    raw, kernel = args.input.read_bytes(), args.kernel.read_bytes()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for speed in (1, 2):
        out = args.output_dir / f"gpu-benchmark-{speed}.bin"
        out.write_bytes(make_payload(raw, kernel, speed))
        print(f"{out}: {out.stat().st_size} bytes")

if __name__ == "__main__": main()
