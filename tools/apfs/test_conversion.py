#!/usr/bin/env python3
"""Regression cases for preserved packfs extraction and APFS generation."""
import importlib.util
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import apfs
import mkapfs

spec = importlib.util.spec_from_file_location('convert_packfs', HERE / 'convert-packfs.py')
convert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(convert)


def legacy_image(chunked=False):
    content = b'preserved source bytes\n' * 12
    strings = b'\0file\0link\0file'
    nodes, names, data = 4096, 8192, 12288
    payload = struct.pack('<II', 8, 8 + len(content)) + content if chunked else content
    result = bytearray(16384)
    convert.HEADER.pack_into(result, 0, b'PACKFS1\0', 4096, 3, nodes, names, len(strings), data, len(result), 0)
    convert.NODE.pack_into(result, nodes, stat.S_IFDIR | 0o755, 0, 0, 0, 2, 1, 0, 0, 0, 0, 123, 0)
    convert.NODE.pack_into(result, nodes + convert.NODE.size,
                           stat.S_IFREG | 0o640, 501, 20, 0, len(content), data, 0, 1, 4, 0, 123, int(chunked))
    convert.NODE.pack_into(result, nodes + 2 * convert.NODE.size,
                           stat.S_IFLNK | 0o777, 501, 20, 0, 4, 11, 0, 6, 4, 0, 123, 0)
    result[names:names + len(strings)] = strings
    result[data:data + len(payload)] = payload
    return bytes(result), content


class ConversionTests(unittest.TestCase):
    def test_extract_plain_and_chunked_with_metadata(self):
        for chunked in (False, True):
            with self.subTest(chunked=chunked), tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary)
                root = work / 'root'
                root.mkdir()
                image, content = legacy_image(chunked)
                convert.Packfs(image, 0, len(image)).extract(root, work / 'manifest')
                self.assertEqual((root / 'file').read_bytes(), content)
                self.assertEqual((root / 'link').readlink(), Path('file'))
                tree = mkapfs.read_tree(root)
                mkapfs.apply_manifest(tree, work / 'manifest')
                inode = tree.children['file']
                self.assertEqual((inode.uid, inode.gid, inode.mode), (501, 20, stat.S_IFREG | 0o640))
                self.assertEqual((tree.uid, tree.gid), (0, 0))

    def test_real_apfs_round_trip_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source, output = work / 'source.packfs', work / 'root.apfs'
            image, content = legacy_image(True)
            source.write_bytes(image)
            subprocess.run([sys.executable, str(HERE / 'convert-packfs.py'), str(source), str(output),
                            '--volume', 'redwood'], check=True, capture_output=True)
            self.assertEqual(source.read_bytes(), image)
            container = apfs.Container(str(output))
            try:
                volume = apfs.pick_volume(container, None)
                hit = volume.lookup('/file')
                self.assertIsNotNone(hit)
                inode = volume.inode(hit[0])
                self.assertEqual(inode.contents(), content)
                self.assertEqual((inode.owner, inode.group, inode.mode), (501, 20, stat.S_IFREG | 0o640))
            finally:
                container.close()

    def test_added_tree_keeps_set_id_bits_root_owned_and_link_replaces_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            source, output, prefix = work / 'source.packfs', work / 'root.apfs', work / 'prefix'
            source.write_bytes(legacy_image()[0])
            (prefix / 'bin').mkdir(parents=True)
            helper = prefix / 'bin' / 'helper'
            helper.write_bytes(b'#!/bin/sh\n')
            helper.chmod(0o4755)
            subprocess.run([sys.executable, str(HERE / 'convert-packfs.py'), str(source), str(output),
                            '--volume', 'redwood', '--add', 'jb=' + str(prefix), '--link', 'file=/jb/bin/helper'],
                           check=True, capture_output=True)
            container = apfs.Container(str(output))
            try:
                volume = apfs.pick_volume(container, None)
                inode = volume.inode(volume.lookup('/jb/bin/helper')[0])
                self.assertEqual((inode.owner, inode.group, inode.mode), (0, 0, stat.S_IFREG | 0o4755))
                self.assertEqual(stat.S_IFMT(volume.inode(volume.lookup('/file')[0]).mode), stat.S_IFLNK)
            finally:
                container.close()

    def test_xnup_ramdisk_extraction(self):
        image, _ = legacy_image()
        body = struct.pack('<16sII', b'ramdisk', len(image), 0) + image + b'\0' * 24
        payload = struct.pack('<II', 0x50554e58, len(body)) + body
        start, size = convert.ramdisk_range(payload)
        self.assertEqual(payload[start:start + size], image)

    def test_unsafe_names_rejected(self):
        for name in ('', '.', '..', '/absolute', 'a/../b', 'a//b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                convert.safe_path(name)

    def test_invalid_parent_and_extent_rejected(self):
        image, _ = legacy_image()
        bad = bytearray(image)
        struct.pack_into('<I', bad, 4096 + convert.NODE.size + 32, 999)
        with self.assertRaises(ValueError):
            convert.Packfs(bad, 0, len(bad)).path(1)
        with self.assertRaises(ValueError):
            convert.Packfs(image, 0, len(image)).bytes(len(image), 1)


if __name__ == '__main__':
    unittest.main()
