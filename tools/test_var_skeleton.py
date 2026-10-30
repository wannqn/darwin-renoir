#!/usr/bin/env python3
"""Exercise the actual archived-root skeleton merge used by userland/build.sh."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'userland/merge-var-skel.py'
merge = runpy.run_path(str(SCRIPT))['merge_skeleton']


class SkeletonTests(unittest.TestCase):
    def test_archived_directory_and_file_rebuild_is_idempotent(self):
        archived = ('d\t755\t501\t501\t/private/var/mobile\n'
                    'd\t755\t501\t501\t/private/var/mobile/tmp\n'
                    'f\t600\t0\t0\t/private/var/mobile/setting\t/var/old-setting\n')
        generated = ('f\t644\t501\t501\t/private/var/mobile/setting\t/var/new-setting\n'
                     'd\t700\t501\t501\t/private/var/mobile/tmp\n')
        first = merge(archived + generated)
        self.assertEqual(first.count('/private/var/mobile/tmp'), 1)
        self.assertIn('d\t700\t501\t501\t/private/var/mobile/tmp\n', first)
        self.assertIn('f\t644\t501\t501\t/private/var/mobile/setting\t/var/new-setting\n', first)
        self.assertNotIn('/var/old-setting', first)
        self.assertEqual(merge(first + generated), first)
        self.assertEqual(merge(first), first)

    def test_last_link_target_and_cross_type_destination_win(self):
        text = ('d\t755\t0\t0\t/private/var/db/timezone\n'
                'd\t755\t0\t0\t/private/var/db/timezone/zoneinfo\n'
                'l\t/old-zoneinfo\t/private/var/db/timezone/zoneinfo\n'
                'l\t/usr/share/zoneinfo.default\t/private/var/db/timezone/zoneinfo\n')
        self.assertEqual(merge(text),
                         'd\t755\t0\t0\t/private/var/db/timezone\n'
                         'l\t/usr/share/zoneinfo.default\t/private/var/db/timezone/zoneinfo\n')

    def test_new_parent_is_hoisted_before_archived_child(self):
        child = 'f\t600\t0\t0\t/private/var/root/.ssh/key\t/var/root/.ssh/key\n'
        root = 'd\t700\t0\t0\t/private/var/root\n'
        ssh = 'd\t700\t0\t0\t/private/var/root/.ssh\n'
        self.assertEqual(merge(child + ssh + root), root + ssh + child)

    def test_unrelated_original_order_is_retained(self):
        text = ('d\t755\t0\t0\t/private/var/z\n'
                'd\t755\t0\t0\t/private/var/a\n')
        self.assertEqual(merge(text), text)

    def test_build_entrypoint_rewrites_real_skeleton_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'var.skel'
            original = ('d\t755\t501\t501\t/private/var/mobile/tmp\n'
                        'd\t700\t501\t501\t/private/var/mobile/tmp\n')
            path.write_text(original)
            subprocess.run([sys.executable, str(SCRIPT), str(path)], check=True)
            self.assertEqual(path.read_text(), 'd\t700\t501\t501\t/private/var/mobile/tmp\n')


if __name__ == '__main__':
    unittest.main()
