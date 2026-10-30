#!/usr/bin/env python3
"""Exercise the real boot CLI against a fake USB transport in an isolated tree."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def container(kernel):
    items = [(b'kernel', kernel), (b'ramdisk', b'password-free root'),
             (b'cmdline', b'-v wifi=1 wifi_mac=02:aa:bb:cc:dd:ee epoch=1\0')]
    body = b''
    for name, data in items:
        body += struct.pack('<16sII', name, len(data), 0) + data + b'\0' * (-len(data) % 16)
    body += b'\0' * 24
    return struct.pack('<II', 0x50554e58, len(body)) + body


def entries(data):
    magic, size = struct.unpack_from('<II', data)
    assert magic == 0x50554e58 and size == len(data) - 8
    result = {}
    offset = 8
    while offset + 24 <= len(data):
        name, size, _ = struct.unpack_from('<16sII', data, offset)
        offset += 24
        name = name.rstrip(b'\0')
        if not name:
            return result
        result[name] = data[offset:offset + size]
        offset += (size + 15) & ~15
    raise AssertionError('Missing container terminator')


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


class BootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='recovery-boot-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for folder in ['recovery/assets', 'userland', 'prebuilt/renoir', 'fw-wifi']:
            (self.root / folder).mkdir(parents=True)
        for name in ['boot.py', 'payload.py']:
            shutil.copyfile(ROOT / 'recovery' / name, self.root / 'recovery' / name)
        (self.root / 'userland/system.packfs').write_bytes(b'archived system image')
        (self.root / 'userland/system.apfs').write_bytes(apfs_image())
        (self.root / 'userland/root.apfs').write_bytes(apfs_image())
        (self.root / 'prebuilt/renoir/resident-usb.img').write_bytes(b'resident loader')
        (self.root / 'prebuilt/mach.development.bcm2837').write_bytes(b'current tested kernel')
        (self.root / 'fw-wifi/mac').write_text('02:aa:bb:cc:dd:ee')
        for name, kernel in [('renoir-ios-share.bin', b'old archived kernel'),
                             ('renoir-phone-good-share.bin', b'earlier fallback kernel')]:
            (self.root / 'recovery/assets' / name).write_bytes(container(kernel))
        self.events = self.root / 'events.jsonl'
        self.state = self.root / 'state'
        fake = self.root / 'fastboot'
        fake.write_text('#!' + sys.executable + '\n' + r'''
import json, os, sys
from pathlib import Path
args=sys.argv[1:]
with Path(os.environ['BOOT_TEST_EVENTS']).open('a') as f:f.write(json.dumps(args)+'\n')
if args[:1]==['-s']:args=args[2:]
state=Path(os.environ['BOOT_TEST_STATE'])
if args==['devices']:
 print(('xnuloader' if state.exists() else 'testserial')+'\tfastboot')
elif args[:1]==['getvar']:
 key=args[1];value=os.environ.get('BOOT_TEST_PRODUCT','renoir')
 print('(bootloader) '+key+': '+value,file=sys.stderr)
elif args[:1]==['boot']:state.write_text('resident')
elif args[:1]==['stage'] and os.environ.get('BOOT_TEST_FAIL_STAGE'):
 print('FAILED (remote: test upload error)',file=sys.stderr);sys.exit(1)
elif args[:1] not in (['stage'],['oem']):sys.exit('Unexpected command')
''')
        fake.chmod(0o755)
        self.env = dict(os.environ, FASTBOOT=str(fake), BOOT_TEST_EVENTS=str(self.events),
                        BOOT_TEST_STATE=str(self.state))
        self.mac = ['--wifi-mac', '02:11:22:33:44:55']

    def run_boot(self, args, input_text=''):
        return subprocess.run([sys.executable, str(self.root / 'recovery/boot.py'), *args],
                              env=self.env, input=input_text, capture_output=True, text=True, timeout=20)

    def calls(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []

    def test_mac_required_even_with_saved_mac(self):
        result = self.run_boot([])
        self.assertEqual(result.returncode, 2)
        self.assertIn('--wifi-mac', result.stderr)
        self.assertFalse(self.calls())

    def test_interactive_mac_prompt(self):
        result = self.run_boot([], '02:11:22:33:44:55\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Enter this', result.stdout)
        payload = entries((self.root / 'recovery/assets/run-current.bin').read_bytes())
        self.assertIn(b'wifi_mac=02:11:22:33:44:55', payload[b'cmdline'])
        self.assertNotIn(b'02:aa:bb:cc:dd:ee', payload[b'cmdline'])

    def test_interactive_invalid_mac_reprompts(self):
        result = self.run_boot([], 'bad\nff:ff:ff:ff:ff:ff\n02:11:22:33:44:55\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('Enter this'), 3)
        self.assertEqual(result.stdout.count('Please try again'), 2)

    def test_interactive_mac_without_colons(self):
        result = self.run_boot([], '021122334455\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('colons optional', result.stdout)
        payload = entries((self.root / 'recovery/assets/run-current.bin').read_bytes())
        self.assertIn(b'wifi_mac=02:11:22:33:44:55', payload[b'cmdline'])

    def test_mac_argument_without_colons(self):
        result = self.run_boot(['--wifi-mac', '021122334455'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = entries((self.root / 'recovery/assets/run-current.bin').read_bytes())
        self.assertIn(b'wifi_mac=02:11:22:33:44:55', payload[b'cmdline'])

    def test_interactive_invalid_then_eof_never_contacts_phone(self):
        result = self.run_boot([], 'bad\n')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.calls())

    def test_bad_mac_never_contacts_phone(self):
        result = self.run_boot(['--wifi-mac', 'ff:ff:ff:ff:ff:ff'])
        self.assertEqual(result.returncode, 2)
        self.assertIn('nonzero unicast', result.stderr)
        self.assertFalse(self.calls())

    def test_default_boot_uses_current_kernel_and_only_supplied_mac(self):
        result = self.run_boot(self.mac)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = entries((self.root / 'recovery/assets/run-current.bin').read_bytes())
        self.assertEqual(payload[b'kernel'], b'current tested kernel')
        self.assertEqual(payload[b'ramdisk'], apfs_image())
        self.assertIn(b'wifi_mac=02:11:22:33:44:55', payload[b'cmdline'])
        self.assertNotIn(b'02:aa:bb:cc:dd:ee', payload[b'cmdline'])
        self.assertEqual(payload[b'cmdline'].count(b'wifi_mac='), 1)
        calls = self.calls()
        stages = [call[-1] for call in calls if 'stage' in call]
        self.assertEqual(Path(stages[0]).name, 'system.apfs')
        self.assertEqual(calls[-1], ['-s', 'xnuloader', 'oem', 'run'])
        for call in calls:
            operation = call[2] if call[:1] == ['-s'] else call[0]
            self.assertIn(operation, ['devices', 'getvar', 'boot', 'oem', 'stage'])

    def test_earlier_fallback_is_explicit(self):
        result = self.run_boot([*self.mac, '--last-phone-good'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = entries((self.root / 'recovery/assets/run-current.bin').read_bytes())
        self.assertEqual(payload[b'kernel'], b'earlier fallback kernel')
        self.assertEqual(payload[b'ramdisk'], b'password-free root')
        stages = [call[-1] for call in self.calls() if 'stage' in call]
        self.assertEqual(Path(stages[0]).name, 'system.packfs')

    def test_bad_apfs_never_contacts_phone(self):
        for name in ('root.apfs', 'system.apfs'):
            target = self.root / 'userland' / name
            target.write_bytes(b'PACKFS1 legacy')
            result = self.run_boot(self.mac)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('APFS', result.stderr)
            self.assertFalse(self.calls())
            target.write_bytes(apfs_image())

    def test_fallback_needs_no_apfs_artifacts(self):
        (self.root / 'userland/root.apfs').unlink()
        (self.root / 'userland/system.apfs').unlink()
        result = self.run_boot([*self.mac, '--last-phone-good'])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_custom_kernel(self):
        kernel = self.root / 'custom.kernel'
        kernel.write_bytes(b'custom rebuilt kernel')
        result = self.run_boot([*self.mac, '--kernel', str(kernel)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = entries((self.root / 'recovery/assets/run-current.bin').read_bytes())
        self.assertEqual(payload[b'kernel'], b'custom rebuilt kernel')

    def test_conflicting_images_never_contacts_phone(self):
        result = self.run_boot([*self.mac, '--kernel', 'anything', '--last-phone-good'])
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.calls())

    def test_similar_model_is_rejected(self):
        self.env['BOOT_TEST_PRODUCT'] = 'renoir-other'
        result = self.run_boot(self.mac)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Wrong device', result.stderr)
        self.assertFalse(any('boot' == part for call in self.calls() for part in call))

    def test_resident_loader_is_not_overwritten(self):
        self.state.write_text('resident')
        result = self.run_boot(self.mac)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stock fastboot', result.stderr)
        self.assertEqual(self.calls(), [['devices']])

    def test_upload_failure_never_runs_kernel(self):
        self.env['BOOT_TEST_FAIL_STAGE'] = '1'
        result = self.run_boot(self.mac)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('test upload error', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(any(call[-2:] == ['oem', 'run'] for call in self.calls()))
        self.assertFalse((self.root / 'recovery/assets/run-current.bin').exists())


if __name__ == '__main__':
    unittest.main()
