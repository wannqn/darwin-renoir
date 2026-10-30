#!/usr/bin/env python3
"""Merge an assembled var.skel in place: last destination wins, parents precede children.

An archived recovery root already contains generated directory/file entries.
Keep its destination ordering where possible, replace entries with regenerated
ones, and hoist any newly appended parent before its existing descendants.
"""
from pathlib import Path
import posixpath
import sys


def merge_skeleton(text):
    entries = {}
    for line in text.splitlines():
        if not line:
            continue
        fields = line.split('\t')
        kind = fields[0]
        if kind == 'l' and len(fields) == 3:
            destination = fields[2]
        elif kind in ('d', 'f') and len(fields) == (5 if kind == 'd' else 6):
            destination = fields[4]
        else:
            raise ValueError('Invalid var.skel entry: ' + repr(line))
        # Dict replacement retains the first position but takes the last value.
        entries[destination] = line

    ordered, emitted = [], set()

    def emit(destination):
        if destination in emitted:
            return
        parent = posixpath.dirname(destination)
        parents = []
        while parent not in ('', '/'):
            if parent in entries:
                parents.append(parent)
            parent = posixpath.dirname(parent)
        for parent in reversed(parents):
            emit(parent)
        emitted.add(destination)
        ordered.append(entries[destination])

    for destination in entries:
        emit(destination)
    return ''.join(line + '\n' for line in ordered)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: merge-var-skel.py VAR.SKEL')
    path = Path(sys.argv[1])
    path.write_text(merge_skeleton(path.read_text()))


if __name__ == '__main__':
    main()
