#!/usr/bin/env python3
"""Convert a preserved packfs (or XNUP ramdisk) to a real read-only APFS container.

No source image is changed. --replace sbin/launchd=userland/obj/stage0 is required
when converting the old system image for APFS boot; its original stage0 mounts packfs.
Use --replace sbin/init=userland/obj/init for the embedded small root's new smoke checks.
--tree retains the extracted tree and owner manifest for independent check-image.sh.
"""
import argparse
import ctypes
import ctypes.util
import mmap
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import subprocess
import sys
import tempfile

HEADER = struct.Struct('<8sIIQQQQQQ')
NODE = struct.Struct('<IIIIQQIIIIQQ')
CHUNK = 65536


def safe_path(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('Unsafe image path: ' + repr(value))
    return path


def ramdisk_range(data):
    if len(data) < 8 or struct.unpack_from('<II', data) != (0x50554e58, len(data) - 8):
        raise ValueError('Invalid XNUP header')
    offset, result, seen = 8, None, set()
    while offset + 24 <= len(data):
        name, size, reserved = struct.unpack_from('<16sII', data, offset)
        offset += 24
        name = name.rstrip(b'\0')
        if not name:
            if size or reserved or offset != len(data) or result is None:
                raise ValueError('Invalid XNUP terminator or missing ramdisk')
            return result
        if name in seen or offset + ((size + 15) & ~15) > len(data):
            raise ValueError('Duplicate or truncated XNUP entry')
        seen.add(name)
        if name == b'ramdisk':
            result = (offset, size)
        offset += (size + 15) & ~15
    raise ValueError('Missing XNUP terminator')


class Packfs:
    def __init__(self, data, start, length):
        self.data, self.start, self.length = data, start, length
        if length < 4096:
            raise ValueError('Truncated packfs')
        magic, block, count, nodes, strings, strings_size, _, image_size, _ = HEADER.unpack_from(data, start)
        if (magic != b'PACKFS1\0' or image_size != length or not count or
                block < 4096 or block & (block - 1) or nodes + count * NODE.size > length or
                strings + strings_size > length):
            raise ValueError('Invalid packfs superblock')
        self.strings, self.strings_size = strings, strings_size
        self.nodes = [NODE.unpack_from(data, start + nodes + i * NODE.size) for i in range(count)]
        if not stat.S_ISDIR(self.nodes[0][0]) or self.nodes[0][6] != 0:
            raise ValueError('Invalid packfs root')
        self.paths = {0: PurePosixPath('.')}
        self.lz4 = self.zstd = None

    def bytes(self, offset, size):
        if offset < 0 or size < 0 or offset > self.length or size > self.length - offset:
            raise ValueError('Packfs extent outside image')
        return self.data[self.start + offset:self.start + offset + size]

    def path(self, index, visiting=None):
        if index in self.paths:
            return self.paths[index]
        visiting = set() if visiting is None else visiting
        if index in visiting or index >= len(self.nodes):
            raise ValueError('Invalid packfs parent chain')
        visiting.add(index)
        node = self.nodes[index]
        if node[7] + node[8] > self.strings_size:
            raise ValueError('Invalid packfs name extent')
        name = self.bytes(self.strings + node[7], node[8]).decode('utf-8')
        safe_path(name)
        if '/' in name or node[6] >= len(self.nodes) or not stat.S_ISDIR(self.nodes[node[6]][0]):
            raise ValueError('Invalid packfs parent or child name')
        result = self.path(node[6], visiting) / name
        visiting.remove(index)
        self.paths[index] = result
        return result

    def decompress(self, source, size, zstd):
        out = ctypes.create_string_buffer(size)
        if zstd:
            if self.zstd is None:
                self.zstd = ctypes.CDLL(ctypes.util.find_library('zstd') or 'libzstd.so.1')
                self.zstd.ZSTD_decompress.restype = ctypes.c_size_t
                self.zstd.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
            result = self.zstd.ZSTD_decompress(out, size, source, len(source))
        else:
            if self.lz4 is None:
                self.lz4 = ctypes.CDLL(ctypes.util.find_library('lz4') or 'liblz4.so.1')
                self.lz4.LZ4_decompress_safe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
            result = self.lz4.LZ4_decompress_safe(source, out, len(source), size)
        if result != size:
            raise ValueError('Invalid compressed packfs chunk')
        return out.raw

    def contents(self, node):
        size, offset, flags = node[4], node[5], node[11]
        if flags & ~3 or flags == 2:
            raise ValueError('Unsupported packfs file flags')
        if not flags:
            for at in range(0, size, CHUNK):
                yield self.bytes(offset + at, min(CHUNK, size - at))
            return
        chunks = (size + CHUNK - 1) // CHUNK
        table = struct.unpack('<%dI' % (chunks + 1), self.bytes(offset, (chunks + 1) * 4))
        if table[0] != (chunks + 1) * 4:
            raise ValueError('Invalid packfs chunk table')
        for i in range(chunks):
            raw_size = min(CHUNK, size - i * CHUNK)
            packed_size = table[i + 1] - table[i]
            if packed_size <= 0 or packed_size > raw_size:
                raise ValueError('Invalid packfs chunk length')
            packed = self.bytes(offset + table[i], packed_size)
            yield packed if packed_size == raw_size else self.decompress(packed, raw_size, bool(flags & 2))

    def extract(self, tree, manifest):
        used, records, directories = set(), [], []
        order = sorted(range(len(self.nodes)), key=lambda i: (len(self.path(i).parts), str(self.path(i))))
        for i in order:
            node, relative = self.nodes[i], self.path(i)
            if str(relative) in used:
                raise ValueError('Duplicate packfs path')
            used.add(str(relative))
            mode, uid, gid = node[:3]
            target = tree / str(relative)
            record = '%o\t%d\t%d\t%s' % (mode, uid, gid, str(relative))
            if stat.S_ISDIR(mode):
                if i:
                    target.mkdir(mode=0o700)
                directories.append((target, mode, node[10]))
            elif stat.S_ISLNK(mode):
                if node[5] + node[4] > self.strings_size:
                    raise ValueError('Invalid packfs symlink extent')
                link = self.bytes(self.strings + node[5], node[4]).decode('utf-8')
                target.symlink_to(link)
                record += '\t' + link
            elif stat.S_ISREG(mode):
                with target.open('xb') as out:
                    for piece in self.contents(node):
                        out.write(piece)
                target.chmod(stat.S_IMODE(mode))
                os.utime(target, (node[10], node[10]))
            else:
                raise ValueError('Unsupported packfs inode type')
            records.append(record + '\n')
        for target, mode, mtime in reversed(directories):
            target.chmod(stat.S_IMODE(mode))
            os.utime(target, (mtime, mtime))
        manifest.write_text(''.join(records))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--extract-only', action='store_true', help='retain source tree and owner manifest without generating an image')
    parser.add_argument('--volume', required=True, choices=['System', 'redwood', 'Probe'])
    parser.add_argument('--ramdisk', action='store_true', help='read the ramdisk entry of an archived XNUP')
    parser.add_argument('--tree', type=Path, help='new directory to retain extracted root/ and manifest')
    parser.add_argument('--replace', action='append', default=[], metavar='PATH=FILE')
    parser.add_argument('--add', action='append', default=[], metavar='PATH=SOURCE',
                        help='a host directory (copied with its links and permission bits) or file put at PATH, '
                             'in place of whatever is there; owned by root:wheel')
    parser.add_argument('--link', action='append', default=[], metavar='PATH=TARGET',
                        help='a symbolic link at PATH to TARGET, in place of a file or link there')
    parser.add_argument('--check', action='store_true', help='independently check output using apfsck and kernel reader')
    args = parser.parse_args()
    if args.extract_only and args.tree is None:
        parser.error('--extract-only requires --tree')
    if not args.extract_only and args.output is None:
        parser.error('OUTPUT is required unless --extract-only')
    if args.output is not None and (args.source.resolve() == args.output.resolve() or args.output.exists()):
        parser.error('Output must be new and different from the preserved source')
    if not args.extract_only and args.volume == 'System' and not any(x.startswith('sbin/launchd=') for x in args.replace):
        parser.error('System conversion requires --replace sbin/launchd=userland/obj/stage0 (the APFS stage0)')
    with tempfile.TemporaryDirectory(prefix='packfs-to-apfs-') as temporary:
        work = args.tree or Path(temporary)
        if args.tree:
            work.mkdir(parents=True, exist_ok=False)
        tree, manifest = work / 'root', work / 'manifest'
        tree.mkdir()
        with args.source.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            start, length = ramdisk_range(data) if args.ramdisk else (0, len(data))
            Packfs(data, start, length).extract(tree, manifest)
        for replacement in args.replace:
            name, filename = replacement.split('=', 1)
            target = tree / str(safe_path(name))
            if target.is_symlink() or not target.is_file():
                raise ValueError('Replacement must name an existing regular file: ' + name)
            # The extracted tree may contain absolute symlinks; never traverse one on the host.
            if any(p.is_symlink() for p in target.parents if p != tree.parent):
                raise ValueError('Replacement traverses a symlink: ' + name)
            shutil.copyfile(filename, target)
        for addition in args.add + args.link:
            name, source = addition.split('=', 1)
            target = tree / str(safe_path(name))
            if any(p.is_symlink() for p in target.parents if p != tree.parent):
                raise ValueError('Addition traverses a symlink: ' + name)
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if addition in args.link:
                target.symlink_to(source)
            elif Path(source).is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target)
        if args.extract_only:
            print(str(work) + ': packfs extracted; source preserved')
            return
        here = Path(__file__).resolve().parent
        temporary_image = args.output.with_name(args.output.name + '.new')
        if temporary_image.exists():
            raise ValueError('Refusing existing temporary output: ' + str(temporary_image))
        spec = args.volume + '=' + str(tree) + ',manifest=' + str(manifest)
        subprocess.run([sys.executable, str(here / 'mkapfs.py'), '-z', '--plain', 'fw',
                        '--plain', 'fw-renoir', '--plain', 'fw-wifi-renoir', '--plain', 'fw-audio-renoir',
                        '-o', str(temporary_image), spec], check=True)
        if args.check:
            subprocess.run(['bash', str(here / 'check-image.sh'), str(temporary_image), spec], check=True)
        os.replace(temporary_image, args.output)
        print(str(args.output) + ': APFS generated; original source preserved')


if __name__ == '__main__':
    main()
