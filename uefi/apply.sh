#!/bin/bash
# Make ../Mu-Silicium: a clone of Project-Silicium/Mu-Silicium at the commit our port was made on,
# with the redwood port (this directory) put into it. See README.md here for how to build it.
set -e
cd "$(dirname "$(readlink -f "$0")")"
DEVICE=${1:-redwood}
case "$DEVICE" in redwood|renoir) ;; *) echo "usage: $0 [redwood|renoir] [--no-submodules]" >&2; exit 1 ;; esac
MU=${MU_DIR:-../Mu-Silicium}
[ -e $MU ] && { echo "uefi/apply.sh: $MU already exists"; exit 1; }
git clone https://github.com/Project-Silicium/Mu-Silicium.git $MU
git -C $MU checkout -q "$(cat BASE)"
if [ "${2:-}" != --no-submodules ]; then
  git -C $MU submodule update --init --recursive
fi
git -C $MU apply --whitespace=nowarn "$PWD/mu-silicium.patch"
if [ "$DEVICE" = renoir ]; then
  git -C "$MU" apply --whitespace=nowarn "$PWD/renoir.patch"
  cp -r files/Silicon/. "$MU/Silicon/"
  # Stage zero must also keep logs in RAM, including a failed payload load.
  python3 - "$MU/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/XnuLoader.h" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('#define XNU_LOG_TO_STORAGE  1', '#define XNU_LOG_TO_STORAGE  0'))
PY
else
  cp -r files/. "$MU/"
fi
echo "$DEVICE" > "$MU/.xnu-device"
echo "uefi/apply.sh: done; next: uefi/README.md"
