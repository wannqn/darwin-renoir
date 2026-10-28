#!/usr/bin/env python3
"""Check actual boot-helper command errors without accessing USB hardware."""
import ast
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import Mock

source = Path(__file__).resolve().parents[1] / 'recovery/boot.py'
tree = ast.parse(source.read_text())
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'cmd')


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.run = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
        module = types.SimpleNamespace(run=self.run, CalledProcessError=subprocess.CalledProcessError,
                                       TimeoutExpired=subprocess.TimeoutExpired)
        env = {'subprocess': module, 'fb': '/usr/bin/fastboot'}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
        self.cmd = env['cmd']

    def test_real_error_visible(self):
        self.run.side_effect = subprocess.CalledProcessError(1, [], stderr='FAILED (remote: bad size)\n')
        with self.assertRaisesRegex(SystemExit, 'remote: bad size'):
            self.cmd('stage', 'system.packfs', serial='xnuloader')

    def test_live_upload(self):
        self.cmd('stage', 'system.packfs', serial='xnuloader', timeout=900, live=True)
        self.run.assert_called_once_with(
            ['/usr/bin/fastboot', '-s', 'xnuloader', 'stage', 'system.packfs'],
            capture_output=False, text=True, timeout=900, check=True)

    def test_timeout(self):
        self.run.side_effect = subprocess.TimeoutExpired([], 900)
        with self.assertRaisesRegex(SystemExit, 'timed out after 900 seconds'):
            self.cmd('stage', 'system.packfs', timeout=900)


if __name__ == '__main__':
    unittest.main()
