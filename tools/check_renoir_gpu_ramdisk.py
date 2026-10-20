#!/usr/bin/env python3
"""Check early GPU firmware is readable in an actual Renoir packfs RAM image.

The kernel's pre-mount firmware reader accepts plain files only, even though
mounted packfs supports LZ4/Zstd. Run this on the image passed to mkpayload.
"""
import hashlib
import stat
import struct
import sys
from pathlib import Path

SUPER = struct.Struct('<8sIIQQQQQQ')
NODE = struct.Struct('<IIIIQQIIIIQQ')

def check(path, firmware):
    data = Path(path).read_bytes()
    if len(data) < 4096:
        raise ValueError('truncated packfs superblock')
    magic, block, count, nodes, strings, strings_size, _, image_size, _ = SUPER.unpack_from(data)
    if (magic != b'PACKFS1\0' or not count or image_size > len(data) or
        nodes + count * NODE.size > image_size or strings + strings_size > image_size):
        raise ValueError('invalid packfs bounds')
    entries = [NODE.unpack_from(data, nodes+i*NODE.size) for i in range(count)]
    def child(parent, name):
        for i,n in enumerate(entries):
            if i == parent or n[6] != parent:
                continue
            if n[7] + n[8] > strings_size:
                raise ValueError('invalid packfs name bounds')
            if data[strings+n[7]:strings+n[7]+n[8]] == name.encode():
                return i
        raise ValueError('missing '+name)
    directory = child(0, 'fw-renoir')
    if not stat.S_ISDIR(entries[directory][0]):
        raise ValueError('fw-renoir is not a directory')
    for name in ('a660_gmu.bin','a660_sqe.fw','a660_zap.elf'):
        n = entries[child(directory,name)]
        if not stat.S_ISREG(n[0]) or n[11] != 0:
            raise ValueError(name+': early GPU reader requires an uncompressed regular file')
        if not n[4] or n[5]+n[4] > image_size:
            raise ValueError(name+': invalid firmware extent')
        actual=data[n[5]:n[5]+n[4]]
        expected=(Path(firmware)/name).read_bytes()
        if actual != expected:
            raise ValueError(name+': differs from local Renoir firmware')
        print(name, len(actual), 'plain, SHA256',hashlib.sha256(actual).hexdigest())

if __name__ == '__main__':
    if len(sys.argv) not in (2,3):
        sys.exit('usage: check_renoir_gpu_ramdisk.py RAM.packfs [fw-gpu/renoir]')
    try:
        check(sys.argv[1],sys.argv[2] if len(sys.argv)==3 else Path(__file__).resolve().parents[1]/'fw-gpu/renoir')
    except (ValueError,OSError,struct.error) as error:
        sys.exit(str(error))
