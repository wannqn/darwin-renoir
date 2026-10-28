# Darwin for Renoir

Experimental iOS 16.5 / Darwin port for **Xiaomi Mi 11 Lite 5G (renoir, SM7350)**.
Boots through a custom Project Silicium UEFI. **RAM boot only: no flashing or erasing.**

## Repository layout

- [`renoir`](https://github.com/wannqn/darwin-renoir/tree/renoir): kernel patches, drivers, userland tools and recovery scripts.
- [`silicium-renoir`](https://github.com/wannqn/darwin-renoir/tree/silicium-renoir): custom UEFI / BootShim / XNU loader sources.
- [Recovery release](https://github.com/wannqn/darwin-renoir/releases/tag/renoir-recovery-20261022): ready-built RAM images, native firmware and build inputs (~3.6 GB).

## Restore and boot

To build without downloading this repository's recovery release, follow the
[source build guide](recovery/BUILD-FROM-SOURCE.md). Renoir GPU, Wi-Fi, audio and
camera vendor inputs are included in Git; Apple iOS files and build tools are fetched separately.

Requires Linux/WSL, Python 3.12+, GitHub CLI, platform-tools and ~20 GB free space.
The repository is private; authenticate with `gh auth login` first.

```sh
git clone --branch renoir --single-branch https://github.com/wannqn/darwin-renoir.git
cd darwin-renoir
python3 recovery/restore.py --build-inputs
# Put the phone in stock fastboot mode.
python3 recovery/boot.py
```

The script asks for your handset's device Wi-Fi MAC from Android before booting.
**Colons are optional:** enter `AABBCCDDEEFF` or `AA:BB:CC:DD:EE:FF`.
You can also supply it with `--wifi-mac AA:BB:CC:DD:EE:FF`. The helper uses the
current prebuilt kernel. Add `--last-phone-good` to explicitly select the earlier
archived kernel/root.
Wi-Fi passwords and private keys are excluded; configure Wi-Fi manually after boot.

## Status

Earlier phone tests confirmed UI/touch, GPU, Wi-Fi, speakers, battery reporting,
main/front camera preview, photos and autofocus. Current Wi-Fi fixes are confirmed
on a second Renoir: 2.4/5 GHz scans, open and WPA2 joining, and Safari internet access.
The final kernel was tested through resident RAM reloads; complete cold-boot and
other upstream integration regressions remain pending.
Bluetooth, cellular, APFS/persistent boot and 90 Hz are not ready.

[Recovery & rebuild guide](recovery/README.md) · [Port details](docs/renoir.md) ·
[Latest integration report](docs/upstream-20261021.md) · [Upstream reference](docs/upstream-reference.md)

Based on Apple XNU, the original darwin-redwood port and Project Silicium.
