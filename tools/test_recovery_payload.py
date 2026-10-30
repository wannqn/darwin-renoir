#!/usr/bin/env python3
"""Check recovery container edits, including resized kernels and boot arguments."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recovery'))
from payload import prepare, validate_apfs, validate_mac


def pack(items):
    body = b''
    for name, data in items:
        body += struct.pack('<16sII', name, len(data), 0) + data + b'\0' * (-len(data) % 16)
    body += b'\0' * 24
    return struct.pack('<II', 0x50554e58, len(body)) + body


def unpack(data):
    magic, size = struct.unpack_from('<II', data)
    assert magic == 0x50554e58 and size == len(data) - 8
    result = {}
    offset = 8
    while offset + 24 <= len(data):
        name, size, reserved = struct.unpack_from('<16sII', data, offset)
        offset += 24
        name = name.rstrip(b'\0')
        if not name:
            assert offset == len(data)
            return result
        result[name] = data[offset:offset + size]
        offset += (size + 15) & ~15
    raise AssertionError('Missing terminator')


def apfs_image():
    header = bytearray(4096)
    header[32:36] = b'NXSB'
    struct.pack_into('<IQ', header, 36, 4096, 1)
    first = second = 0
    for word in struct.unpack_from('<1022I', header, 8):
        first = (first + word) % 0xffffffff
        second = (second + first) % 0xffffffff
    low = 0xffffffff - (first + second) % 0xffffffff
    high = 0xffffffff - (first + low) % 0xffffffff
    struct.pack_into('<Q', header, 0, (high << 32) | low)
    return bytes(header)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.items = [(b'kernel', b'old kernel'), (b'ramdisk', bytes(range(255))),
                      (b'cmdline', b'-v wifi=1 wifi_mac=02:11:22:33:44:55 epoch=1\0')]
        self.data = pack(self.items)

    def test_different_handset_and_kernel(self):
        kernel = b'new kernel' * 123
        result = unpack(prepare(self.data, 1234567890, '02:AA:BB:CC:DD:EE', kernel))
        self.assertEqual(result[b'kernel'], kernel)
        self.assertEqual(result[b'ramdisk'], self.items[1][1])
        self.assertEqual(result[b'cmdline'],
                         b'-v wifi=1 epoch=1234567890 wifi_mac=02:aa:bb:cc:dd:ee\0')
    def test_original_boot_options_survive_repeated_preparation(self):
        data = pack(self.items[:2] + [(b'cmdline', b'-v cpus=4 touch_lat=1 fb_filter=0\0')])
        result = unpack(prepare(prepare(data, 1), 2))[b'cmdline'].split()
        self.assertIn(b'cpus=4', result)
        self.assertNotIn(b'cpus=8', result)
        self.assertEqual(result.count(b'touch_lat=1'), 1)
        self.assertEqual(result.count(b'fb_filter=0'), 1)

    def test_current_ram_boot_uses_all_cores_without_changing_fallback(self):
        data = pack(self.items[:2] + [(b'cmdline', b'-v cpus=4 touch_lat=1\0')])
        current = prepare(data, 1, cpu_count=8)
        words = unpack(prepare(current, 2))[b'cmdline'].split()
        self.assertEqual([word for word in words if word.startswith(b'cpus=')], [b'cpus=8'])
        self.assertIn(b'touch_lat=1', words)
        fallback = unpack(prepare(data, 1))[b'cmdline'].split()
        self.assertIn(b'cpus=4', fallback)
    def test_epoch_refresh_preserves_mac_and_kernel(self):
        first = prepare(self.data, 2, '02:aa:bb:cc:dd:ee', b'new')
        result = unpack(prepare(first, 9876543210))
        self.assertEqual(result[b'kernel'], b'new')
        self.assertIn(b'wifi_mac=02:aa:bb:cc:dd:ee', result[b'cmdline'])
        self.assertEqual(result[b'cmdline'].count(b'epoch='), 1)

    def test_extra_boot_args_replace_same_name_and_survive_epoch_refresh(self):
        data = pack(self.items[:2] + [(b'cmdline', b'-v touchscreen=1 fb_double=1 epoch=1\0')])
        first = prepare(data, 2, cpu_count=8, boot_args=['touchscreen=0', 'touch_lat=1', 'cpus=4'])
        words = unpack(prepare(first, 3))[b'cmdline'].rstrip(b'\0').split()
        self.assertEqual([w for w in words if w.startswith(b'touchscreen=')], [b'touchscreen=0'])
        self.assertEqual([w for w in words if w.startswith(b'cpus=')], [b'cpus=4'])
        self.assertIn(b'touch_lat=1', words)
        self.assertIn(b'fb_double=1', words)
        self.assertEqual([w for w in words if w.startswith(b'epoch=')], [b'epoch=3'])
        with self.assertRaisesRegex(ValueError, 'Invalid boot argument'):
            prepare(data, 1, boot_args=['two words'])

    def test_apfs_ramdisk_replaces_legacy_embedded_root(self):
        root = apfs_image()
        result = unpack(prepare(self.data, 1, kernel=b'APFS kernel', ramdisk=root))
        self.assertEqual(result[b'ramdisk'], root)
        self.assertEqual(result[b'kernel'], b'APFS kernel')
        self.assertEqual(unpack(self.data)[b'ramdisk'], self.items[1][1])

    def test_apfs_replacement_requires_embedded_ramdisk(self):
        with self.assertRaisesRegex(ValueError, 'no ramdisk'):
            prepare(pack([self.items[0], self.items[2]]), 1, ramdisk=apfs_image())

    def test_apfs_rejects_packfs_truncation_checksum_and_length(self):
        image = apfs_image()
        corrupt = bytearray(image)
        corrupt[80] ^= 1
        for data, length in [(b'PACKFS1', 4096), (image[:100], 4096),
                             (corrupt, 4096), (image, 8192)]:
            with self.subTest(length=length, size=len(data)), self.assertRaises(ValueError):
                validate_apfs(data, length)
        validate_apfs(image, len(image))

    def test_bad_inputs(self):
        for data in (b'', self.data[:-1], b'FAIL' + self.data[4:],
                     pack(self.items + [self.items[0]]), pack(self.items[:2])):
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                prepare(data, 1)
        with self.assertRaises(ValueError):
            prepare(self.data, 1, kernel=b'')

    def test_invalid_mac(self):
        for mac in ('', '00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff',
                    '01:22:33:44:55:66', '02:aa:bb:cc:dd:ee wifi=0',
                    '000000000000', 'ffffffffffff', '012233445566',
                    '02112233445', '02:1122334455'):
            with self.subTest(mac=mac), self.assertRaises(ValueError):
                validate_mac(mac)

    def test_colons_optional_and_normalized(self):
        for mac in ('021122334455', '021122334455\n', '02:11:22:33:44:55',
                    '02AABBCCDDEE', '02:AA:BB:CC:DD:EE'):
            expected = '02:aa:bb:cc:dd:ee' if 'aa' in mac.lower() else '02:11:22:33:44:55'
            self.assertEqual(validate_mac(mac), expected)
        result = unpack(prepare(self.data, 1, wifi_mac='021122334455'))
        self.assertIn(b'wifi_mac=02:11:22:33:44:55', result[b'cmdline'])


if __name__ == '__main__':
    unittest.main()
