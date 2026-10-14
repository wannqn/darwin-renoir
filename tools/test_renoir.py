#!/usr/bin/env python3
"""Host checks for board selection and Android boot-image packaging; no phone access."""
import gzip
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class RenoirTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy(REPO / 'mkxnuimg.py', self.root)

    def tearDown(self):
        self.temp.cleanup()

    def pack(self, *args):
        return subprocess.run(['python3', str(self.root / 'mkxnuimg.py'), *args],
                              capture_output=True, text=True)

    def test_renoir_refuses_redwood_prebuilt(self):
        result = self.pack('--device', 'renoir')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('redwood prebuilt is incompatible', result.stderr)
        self.assertFalse((self.root / 'xnu-renoir.img').exists())

    def test_rejects_other_device_tree(self):
        mu = self.root / 'Mu-Silicium'
        mu.mkdir()
        (mu / '.xnu-device').write_text('redwood\n')
        result = self.pack('--device', 'renoir')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('different device', result.stderr)

    def test_renoir_image_uses_renoir_dtb(self):
        mu = self.root / 'Mu-Silicium'
        fv = mu / 'Build/renoirPkg/RELEASE_CLANGPDB/FV'
        fv.mkdir(parents=True)
        (mu / '.xnu-device').write_text('renoir\n')
        (fv / 'SILICIUM_UEFI.fd').write_bytes(bytes(0x200000))
        shim = mu / 'BootShim'
        shim.mkdir()
        (shim / 'Makefile').write_text('all:\n\tprintf shim > BootShim.bin\n')
        dtbs = mu / 'Resources/DTBs'
        dtbs.mkdir(parents=True)
        (dtbs / 'renoir.dtb').write_bytes(b'renoir-dtb-fixture')
        (dtbs / 'redwood.dtb').write_bytes(b'wrong-board')
        scripts = mu / 'Resources/Scripts'
        scripts.mkdir()
        shutil.copy(REPO / 'prebuilt/uefi/mkbootimg.py', scripts)
        (mu / 'Resources/ramdisk').write_bytes(b'ramdisk')
        result = self.pack('--device', 'renoir')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = (self.root / 'xnu-renoir.img').read_bytes()
        self.assertEqual(data[:8], b'ANDROID!')
        size = struct.unpack_from('<I', data, 8)[0]
        page_size = struct.unpack_from('<I', data, 36)[0]
        kernel = data[page_size:page_size + size]
        self.assertTrue(kernel.endswith(b'renoir-dtb-fixture'))
        self.assertEqual(gzip.decompress(kernel[:-len(b'renoir-dtb-fixture')]),
                         b'shim' + bytes(0x200000))

    def test_board_property_is_fail_closed(self):
        # Compile the actual kernel helper with a DT provider. Test absent,
        # truncated and unterminated firmware properties as well as both boards.
        source = (REPO / 'xnu/files/bsd/dev/redwood_input.c').read_text()
        helper = source[source.index('bool\nredwood_board_is'):source.index('static LCK_GRP_DECLARE')]
        program = r'''
#include <stdbool.h>
#include <string.h>
#include <assert.h>
typedef void *DTEntry;
enum { kSuccess = 0 };
static const void *property;
static unsigned int property_size;
int SecureDTLookupEntry(void *a, const char *b, DTEntry *c) { *c = 0; return 0; }
int SecureDTGetProperty(DTEntry a, const char *b, const void **c, unsigned int *d) {
    *c = property; *d = property_size; return property ? 0 : -1;
}
''' + helper + r'''
int main(void) {
    assert(!redwood_board_is("redwood"));
    property = "renoir"; property_size = 7;
    assert(redwood_board_is("renoir")); assert(!redwood_board_is("redwood"));
    property_size = 6; assert(!redwood_board_is("renoir"));
    property = "renoirX"; property_size = 7; assert(!redwood_board_is("renoir"));
    property = "redwood"; property_size = 8;
    assert(redwood_board_is("redwood")); assert(!redwood_board_is("renoir"));
    return 0;
}
'''
        cfile = self.root / 'board.c'
        cfile.write_text(program)
        subprocess.run(['clang', '-Wall', '-Werror', str(cfile), '-o', str(self.root / 'board')], check=True)
        subprocess.run([str(self.root / 'board')], check=True)


if __name__ == '__main__':
    unittest.main()
