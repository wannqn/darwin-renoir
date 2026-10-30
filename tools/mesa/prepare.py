#!/usr/bin/env python3
"""Prepare fresh Mesa26 source: verified donor patch once, then Renoir's board patch.

Called by tools/mk-mesa.sh. The donor manifest describes the source before the
Renoir adaptation; verify it before applying that adaptation, never after.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

SOURCE = Path(__file__).resolve().parent / 'mesa26'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((SOURCE / 'SOURCE-MANIFEST.json').read_text())
    version = manifest['upstream_version']
    with args.archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['upstream_archive_sha256']:
            raise SystemExit('Mesa archive SHA-256 mismatch')
    out = args.output.resolve()
    if out.name != f'mesa-{version}' or out.exists():
        raise SystemExit(f'Use a fresh mesa-{version} output directory')
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.archive) as archive:
        if not all(Path(member.name).parts[0] == out.name for member in archive.getmembers()):
            raise SystemExit('Unexpected Mesa archive root')
        archive.extractall(out.parent, filter='data')

    def apply(name):
        subprocess.run(['patch', '--batch', '--forward', '--no-backup-if-mismatch',
                        '-p1', '-i', str(SOURCE / name)], cwd=out, check=True)

    apply(f'mesa-{version}-op13.patch')
    for entry in manifest['changed_files']:
        data = (out / entry['path']).read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise SystemExit(f'Donor Mesa source manifest mismatch: {entry["path"]}')
    apply('renoir-a642.patch')
    print(f'Prepared Mesa {version}: verified donor source plus Renoir A642')


if __name__ == '__main__':
    main()
