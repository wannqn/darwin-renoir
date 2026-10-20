#!/usr/bin/env python3
"""Fetch checksum-pinned public Renoir sensor modules into ignored fw-camera/renoir.
Does not access a phone. The resulting binaries/tables are not repository sources.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tuning', action='store_true', help='also verify native colour tuning and actuator metadata')
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name('renoir-camera-modules.json').read_text())
    if args.tuning:
        manifest += json.loads(Path(__file__).with_name('renoir-camera-tuning.json').read_text())
    dest = repo / 'fw-camera' / 'renoir'
    dest.mkdir(parents=True, exist_ok=True)
    for item in manifest:
        path = dest / Path(item['path']).name
        data = path.read_bytes() if path.exists() else None
        if data is None:
            with urllib.request.urlopen(item['url'], timeout=45) as response:
                data = response.read(item['bytes'] + 1)
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256'] or blob != item['git_blob']:
            raise SystemExit('Unexpected vendor module: ' + path.name + '; do not use it before review')
        if not path.exists():
            path.write_bytes(data)
        if path.name.startswith('com.qti.sensormodule.'):
            subprocess.run([sys.executable, str(Path(__file__).with_name('camsensor.py')), str(path), str(path.with_suffix('.tab'))], check=True)
        elif path.name.startswith('com.qti.tuned.'):
            subprocess.run([sys.executable, str(Path(__file__).with_name('camtuning.py')), str(path), str(path.with_suffix('.isp')), '--lsc', 'lsc40'], check=True)
    print('All four public sensor modules verified. Phone sensor IDs still need hardware confirmation.')


if __name__ == '__main__':
    main()
