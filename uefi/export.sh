#!/bin/bash
# Save our changes to the Mu-Silicium tree (../Mu-Silicium, a clone of Project-Silicium/Mu-Silicium
# with the redwood port in it) into this directory: mu-silicium.patch for the files that upstream
# has, files/ for the ones it does not. apply.sh puts them into a fresh clone.
set -e
cd "$(dirname "$(readlink -f "$0")")"
MU=../Mu-Silicium
if [ -f "$MU/.xnu-device" ] && [ "$(cat "$MU/.xnu-device")" = renoir ]; then
  # renoir already exists upstream; only its memory reservation belongs in an overlay.
  git -C "$MU" diff -- Platforms/Xiaomi/renoirPkg > renoir.patch
  git -C "$MU" diff -- BootShim Silicon > mu-silicium.patch
  cp "$MU/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/XnuLoader.c" \
    files/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/
  # Keep the shared header's redwood default; apply.sh selects RAM-only logs for renoir.
  sed 's/#define XNU_LOG_TO_STORAGE  0/#define XNU_LOG_TO_STORAGE  1/' \
    "$MU/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/XnuLoader.h" > \
    files/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/XnuLoader.h
  git -C "$MU" rev-parse HEAD > BASE
  echo "uefi/export.sh: saved renoir changes"
  exit 0
fi
git -C $MU rev-parse HEAD > BASE
git -C $MU diff -- BootShim Silicon > mu-silicium.patch
rm -rf files
mkdir -p files/Resources/Configs files/Resources/DTBs files/Platforms/Xiaomi files/Binaries \
	files/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib
cp -r $MU/Platforms/Xiaomi/redwoodPkg files/Platforms/Xiaomi/
cp $MU/Resources/Configs/redwood.toml files/Resources/Configs/
cp $MU/Resources/DTBs/redwood.dtb files/Resources/DTBs/
cp $MU/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/XnuLoader.[ch] files/Silicon/Silicium/SiliciumPkg/Library/BootManagerLib/
cp -r $MU/Binaries/redwood files/Binaries/
find files -name __pycache__ -prune -exec rm -rf {} +
echo "uefi/export.sh: base $(cut -c1-12 BASE), patch $(wc -l < mu-silicium.patch) lines, $(find files -type f | wc -l) files"
