#!/usr/bin/env python3
"""Check Renoir GPU firmware in the actual APFS image passed to mkpayload.

Firmware is deliberately kept uncompressed in one extent so redwood_image_file
can return a pointer into the resident RAM image without allocation or copying.
"""
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'apfs'))
import apfs


def check(path, firmware):
    container = apfs.Container(str(path))
    try:
        volume = apfs.pick_volume(container, None)
        for name in ('a660_gmu.bin', 'a660_sqe.fw', 'a660_zap.elf'):
            hit = volume.lookup('/fw-renoir/' + name)
            if hit is None:
                raise ValueError('missing fw-renoir/' + name)
            inode = volume.inode(hit[0])
            if not inode.is_reg or inode.decmpfs is not None or not inode.size:
                raise ValueError(name + ': expected an uncompressed nonempty regular file')
            extents = volume.extents(inode.private_id)
            if len(extents) != 1 or extents[0][0] != 0 or not extents[0][2] or extents[0][1] < inode.size:
                raise ValueError(name + ': firmware is not in one contiguous extent')
            actual = inode.contents()
            expected = (Path(firmware) / name).read_bytes()
            if actual != expected:
                raise ValueError(name + ': differs from local Renoir firmware')
            print(name, len(actual), 'APFS plain, SHA256', hashlib.sha256(actual).hexdigest())
    finally:
        container.close()


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        sys.exit('usage: check_renoir_gpu_ramdisk.py RAM.apfs [fw-gpu/renoir]')
    try:
        check(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else Path(__file__).resolve().parents[1] / 'fw-gpu/renoir')
    except (ValueError, OSError, apfs.ApfsError) as error:
        sys.exit(str(error))
