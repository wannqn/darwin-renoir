#!/usr/bin/env python3
"""Build and exercise Bluetooth H4 probe framing without touching a phone."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='renoir-bt-') as tmp:
    exe = Path(tmp) / 'test-h4'
    compiler = shlex.split(os.environ.get('CC', 'cc'))
    subprocess.run(compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-g',
                   str(root / 'tools/bt-test/test_h4.c'), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
