# Renoir recovery

This private backup has two source branches: `renoir` and `silicium-renoir`.
Release: `renoir-recovery-20261022`. Needs Linux/WSL, Python 3.12+, GitHub CLI,
Git, platform-tools and about20 GB free space.

## Ready-to-run restore

```sh
gh auth login
git clone --branch renoir --single-branch https://github.com/wannqn/darwin-renoir.git
cd darwin-renoir
python3 recovery/restore.py --build-inputs
```

The script verifies SHA256 for seven release assets, restores both packfs images,
native Renoir firmware and build tools, and relocates SDK symlinks.
Passwords, SSH keys and access tokens are excluded. Select your Wi-Fi network
and enter its password in iOS. The radio MAC required by this device is preserved.

Put the phone in **stock fastboot** and run:

```sh
python3 recovery/boot.py
# Or use the preserved earlier phone-tested kernel/root:
python3 recovery/boot.py --last-phone-good
```

The helper validates the model and uses only `fastboot boot`, RAM uploads and
`oem run`. It refuses to overwrite a running resident loader. Windows fastboot.exe
at C:/platform-tools is supported from WSL. Reboot normally to return to Android.
iOS changes are volatile; this is not an Android data backup.

## Custom UEFI source

From the kernel clone:

```sh
git clone --branch silicium-renoir --single-branch --recursive https://github.com/wannqn/darwin-renoir.git Mu-Silicium
python3 Mu-Silicium/Recovery/prepare.py
```

The helper reapplies local Mu_Basecore changes missing from an ordinary recursive
clone. A ready-built loader is already in prebuilt/renoir. The failed90 Hz
experiment is archived separately and is not enabled in the working configuration.

## Rebuilding

Build inputs include Theos SDK/toolchain, XNU host tools/libraries and QEMU.
Install Linux packages as needed: clang, lld, llvm, make, cc/c++, git, curl, Python,
7z, flex, bison, autoconf, automake, nasm, pkg-config. Use the WSL Linux filesystem.

```sh
bash xnu/apply.sh
./xnu-build.sh -j6
bash xnuloader/build.sh renoir
```

To rebuild userland, fetch original Apple inputs again with `bash ios165/fetch.sh`;
ready-built packfs images do not require that download. Rebuild Mesa first:

```sh
bash tools/mk-mesa.sh
GL=1 REST=1 WIFID=1 SHARE=1 RC_JOBS=rc.jobs.renoir bash userland/build.sh
QEMU_RAM_GB=6 CMDLINE=-v bash qemu/run-ios.sh 600
```

Latest source changes passed builds and QEMU UI tests, not a new hardware test.
QEMU does not validate physical Renoir drivers. The earlier phone-tested payload
is preserved as a fallback, with its Wi-Fi password removed.

Before deleting local work, verify both branches and all seven assets plus
SHA256SUMS. Keep access to your GitHub account. Old logs/RAW captures, Apple IPSW
source inputs and build caches are not archived.
