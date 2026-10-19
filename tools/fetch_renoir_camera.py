#!/usr/bin/env python3
"""Fetch checksum-pinned public Renoir sensor modules into ignored fw-camera/renoir.
Does not access a phone. The resulting binaries/tables are not repository sources.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


def main():
    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads(Path(__file__).with_name('renoir-camera-modules.json').read_text())
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
        subprocess.run([sys.executable, str(Path(__file__).with_name('camsensor.py')),
                        str(path), str(path.with_suffix('.tab'))], check=True)
    print('All four public sensor modules verified. Phone sensor IDs still need hardware confirmation.')


if __name__ == '__main__':
    main()
