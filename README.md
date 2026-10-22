# Renoir custom UEFI

Project Silicium source snapshot for **Mi 11 Lite 5G (renoir)** and RAM-only iOS boot.
Contains our BootShim payload placement, XNU BootManager dispatch and memory map.

Kernel, drivers and ready-built recovery images live on the
[`renoir` branch](https://github.com/wannqn/darwin-renoir/tree/renoir).
This branch contains the UEFI source only.

## Restore source

```sh
git clone --branch silicium-renoir --single-branch --recursive https://github.com/wannqn/darwin-renoir.git Mu-Silicium
cd Mu-Silicium
python3 Recovery/prepare.py
```

`prepare.py` restores the saved local Mu_Basecore patch; a recursive clone alone
is not enough. Submodules remain pinned to their original revisions.

## Build

```sh
python3 -m venv venv
venv/bin/pip install -r pip-requirements.txt
PATH="$PWD/venv/bin:$PATH" python3 build_uefi.py -d renoir -r RELEASE
```

See [recovery details](Recovery/README.md) and the [upstream build guide](Building.md).
Keep `USE_CUSTOM_DISPLAY_DRIVER=0`; the90 Hz experiment is not working.
Use `fastboot boot` only. Never flash, erase or repartition.

Based on [Project Silicium](https://github.com/Project-Silicium/Mu-Silicium).
The original README is preserved [here](Recovery/UPSTREAM-README.md).
