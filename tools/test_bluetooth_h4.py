#!/usr/bin/env python3
"""Exercise Bluetooth H4, hardware-survey and GENI FIFO cores without a phone."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='renoir-bt-') as tmp:
    compiler = shlex.split(os.environ.get('CC', 'cc'))
    for name in ('h4', 'survey', 'geni', 'query', 'firmware'):
        exe = Path(tmp) / ('test-' + name)
        subprocess.run(compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror',
                   '-fsanitize=address,undefined', '-g',
                   str(root / ('tools/bt-test/test_' + name + '.c')), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
        print(result.stdout.strip().splitlines()[-1])
