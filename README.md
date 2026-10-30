# Darwin for Renoir

Experimental iOS 16.5 / Darwin port for **Xiaomi Mi 11 Lite 5G (renoir, SM7350)**.
Boots through a custom Project Silicium UEFI. **RAM boot only: no flashing or erasing.**

## Repository layout

- [`renoir`](https://github.com/wannqn/darwin-renoir/tree/renoir): kernel patches, drivers, userland tools and recovery scripts.
- [`silicium-renoir`](https://github.com/wannqn/darwin-renoir/tree/silicium-renoir): custom UEFI / BootShim / XNU loader sources.
- [Recovery release](https://github.com/wannqn/darwin-renoir/releases/tag/renoir-recovery-20261022): preserved legacy packfs source images, native firmware and build inputs (~3.6 GB).

## Restore and boot

To build without downloading this repository's recovery release, follow the
[source build guide](recovery/BUILD-FROM-SOURCE.md). Renoir GPU, Wi-Fi, audio and
camera vendor inputs are included in Git; Apple iOS files and build tools are fetched separately.

Requires Linux/WSL, Python 3.12+, GitHub CLI, platform-tools, the restored cross
toolchain and enough space for archived images, extracted trees and APFS outputs.
The repository is private; authenticate with `gh auth login` first.

```sh
git clone --branch renoir --single-branch https://github.com/wannqn/darwin-renoir.git
cd darwin-renoir
python3 recovery/restore.py --build-inputs
# Rebuild the APFS kernel and current userland, converting the preserved images.
# Apply the kernel sources once; an existing source tree must already match this branch.
test -d xnu-src/xnu-8796.121.2 || bash xnu/apply.sh
bash tools/mk-ath11k.sh
./xnu-build.sh -j6
bash tools/mk-mesa.sh
SHARE=1 GL=1 CHECK=1 bash userland/build.sh
SKIP_UEFI=1 bash tools/update-prebuilt.sh
# Only after those steps, put the phone in stock fastboot mode.
python3 recovery/boot.py
```

The script asks for your handset's device Wi-Fi MAC from Android before booting.
**Colons are optional:** enter `AABBCCDDEEFF` or `AA:BB:CC:DD:EE:FF`.
You can also supply it with `--wifi-mac AA:BB:CC:DD:EE:FF`. The helper uses the
current rebuilt APFS kernel with `userland/system.apfs` as `/` and
`userland/root.apfs` as `/redwood`; `/private/var` remains writable ramfs.
Restoring the release alone is not sufficient for this default boot.
Add `--last-phone-good` to explicitly select the earlier archived kernel/root
**together with preserved `userland/system.packfs`**. Never mix that legacy
kernel/root with APFS images. The original recovery payloads and packfs inputs
remain unchanged.
Wi-Fi passwords and private keys are excluded; configure Wi-Fi manually after boot.

## Status

Earlier packfs phone tests confirmed UI/touch, GPU, Wi-Fi, speakers, battery reporting,
main/front camera preview, photos and autofocus. They are historical results,
not a full regression pass for the new combination.

The APFS images passed independent `apfsck` and kernel-reader content checks.
QEMU and a physical Renoir RAM boot confirmed read-only APFS on `/` and `/redwood`,
writable ramfs on `/private/var`, and successful var write/read/unlink. The phone
reported **40 checks, 0 failed** after Android/SurfaceFlinger initialization and a
fresh resident-loader start. GPU initialization reached step 21; CoreAnimation
drew through hardware OpenGL ES 3.2, Mesa 26.2.5, FD642. A screenshot showed the
home screen with intact icons, text and wallpaper; two widgets remained partly
unloaded. This proves the observed boot/rendering path, not improved performance,
less tearing or a complete system regression. Bluetooth, cellular,
persistent-storage APFS boot and 90 Hz remain unready. All APFS images are uploaded
to RAM only.

[Recovery & rebuild guide](recovery/README.md) · [Port details](docs/renoir.md) ·
[Latest integration report](docs/upstream-20261021.md) · [Upstream reference](docs/upstream-reference.md)

Based on Apple XNU, the original darwin-redwood port and Project Silicium.
