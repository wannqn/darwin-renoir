#!/usr/bin/env python3
"""Read Android camera inventory and vendor sensor modules; writes only to the host.
Run with Python on Windows, or point --adb to a usable adb executable.
Outputs are intentionally kept in ignored logs/ and fw-camera/renoir/.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--port', default='5037')
    parser.add_argument('--serial', default='da9ae82c')
    args = parser.parse_args()
    base = [args.adb, '-P', args.port, '-s', args.serial]
    repo = Path(__file__).resolve().parents[1]
    out = repo / 'logs' / 'renoir-camera-android'
    fw = repo / 'fw-camera' / 'renoir'
    out.mkdir(parents=True, exist_ok=True)
    fw.mkdir(parents=True, exist_ok=True)

    def read(command):
        return subprocess.run(base + ['exec-out', 'su', '-c', command],
                              check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=120).stdout

    if read('id').strip().split()[0] != b'uid=0(root)':
        raise SystemExit('Android root required for read-only inventory')
    tasks = {
        'properties.txt': 'getprop',
        'camera-service.txt': 'dumpsys media.camera',
        'kernel-log.txt': 'dmesg',
        'live.dtb': 'cat /sys/firmware/fdt',
        'regulators.txt': 'cat /sys/kernel/debug/regulator/regulator_summary',
    }
    errors = {}
    for name, command in tasks.items():
        try:
            data = read(command)
            (out / name).write_bytes(data)
            print(name, len(data), 'bytes')
        except subprocess.SubprocessError as exc:
            errors[name] = str(exc)
    listing = read('find /vendor/lib64/camera -maxdepth 1 -type f -name "com.qti.sensormodule.*.bin"').decode().splitlines()
    manifest = []
    for remote in listing:
        if not re.fullmatch(r'/vendor/lib64/camera/com\.qti\.sensormodule\.[A-Za-z0-9_.-]+\.bin', remote):
            raise SystemExit('Unexpected sensor module path: ' + repr(remote))
        data = read('cat ' + shlex.quote(remote))
        if not data.startswith(b'QTI Chromatix Header'):
            raise SystemExit('Unexpected sensor module format: ' + remote)
        name = remote.rsplit('/', 1)[1]
        (fw / name).write_bytes(data)
        manifest.append({'path': remote, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        print(name, len(data), 'bytes')
    (out / 'manifest.json').write_text(json.dumps({'modules': manifest, 'errors': errors}, indent=2) + '\n')
    if not manifest:
        raise SystemExit('No sensor modules found; do not guess sensor identities')
    print('Read-only collection complete; sensor tables still require parsing and review.')


if __name__ == '__main__':
    main()
