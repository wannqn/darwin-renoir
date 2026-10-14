#!/usr/bin/env python3
"""Offline layout checks for the a660_* files consumed by this kernel.
This checks file structure and sizes; signature authentication remains TrustZone's job.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys

directory = Path(sys.argv[1] if len(sys.argv) > 1 else 'fw-gpu/renoir')
names = ['a660_gmu.bin', 'a660_sqe.fw', 'a660_zap.mdt', 'a660_zap.b02']
files = {name: (directory / name).read_bytes() for name in names}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


mdt = files['a660_zap.mdt']
require(len(mdt) >= 148 and mdt[:6] == b'\x7fELF\x01\x01', 'zap: expected ELF32 little endian')
offset = struct.unpack_from('<I', mdt, 28)[0]
entry_size, count = struct.unpack_from('<HH', mdt, 42)
require(offset == 52 and entry_size == 32 and count == 3, 'zap: unsupported segment table')
segments = [struct.unpack_from('<8I', mdt, offset + i * entry_size) for i in range(count)]
require(len(mdt) == 52 + 32 * count + segments[1][4] and len(mdt) <= 16384,
        'zap: expected header + hash/certificate block in one kernel page')
require(segments[2][0] == 1 and segments[2][6] & (1 << 27), 'zap: expected relocatable LOAD segment')
require(segments[2][4] == len(files['a660_zap.b02']) and 0 < segments[2][4] <= segments[2][5] <= 4096,
        'zap: b02 length or reserved-memory size mismatch')
sqe = files['a660_sqe.fw']
require(8 <= len(sqe) <= 0x40000 and len(sqe) % 4 == 0, 'SQE: unsupported microcode size')

gmu = files['a660_gmu.bin']
at, blocks, memory = 0, [], []


def in_tcm(start, size):
    return any(base <= start and start + size <= base + 0x4000 for base in (0, 0x10004000))


while at < len(gmu):
    require(len(gmu) - at >= 16, 'GMU: truncated block header')
    address, size, kind, value = struct.unpack_from('<4I', gmu, at)
    at += 16
    require(size <= len(gmu) - at and address + size <= 0x100000000, 'GMU: invalid block extent')
    blocks.append((address, size, kind, value))
    if size == 0 and kind in (1, 7) and not in_tcm(address, 1):
        require(address % 4096 == 0 and 0 < value <= 0x100000, 'GMU: unsupported memory request')
        memory.append((address, (value + 4095) & ~4095))
    at += size
require(len(memory) <= 16, 'GMU: too many memory requests')
for address, size, _, _ in blocks:
    if size and not in_tcm(address, size):
        require(any(base <= address and address + size <= base + length for base, length in memory),
                'GMU: payload has no matching TCM or external-memory request')
print(json.dumps({
    'directory': str(directory), 'gmu_blocks': len(blocks),
    'gmu_external_requests': len(memory), 'zap_load_bytes': segments[2][4],
    'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
              for name, data in files.items()},
}, indent=2))
