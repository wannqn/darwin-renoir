#!/bin/bash
# Copy only regular files. Legacy flat fw-gpu belongs to redwood; renoir never
# falls back to it, even though its firmware uses the same a660_* filenames.
set -e
src=$1
dest=$2
copy_files() {
	local from=$1 to=$2 f
	[ -d "$from" ] || return 0
	mkdir -p "$to"
	for f in "$from"/*; do
		[ ! -f "$f" ] || install -m 0644 "$f" "$to/"
	done
}
copy_files "$src" "$dest/fw"
copy_files "$src/redwood" "$dest/fw"
copy_files "$src/renoir" "$dest/fw-renoir"
