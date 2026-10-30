# Renoir recovery

This private backup has two source branches: `renoir` and `silicium-renoir`.
Release: `renoir-recovery-20261022`. Needs Linux/WSL, Python 3.12+, GitHub CLI,
Git, platform-tools and about20 GB free space.

## Restore archived inputs and prepare APFS

```sh
gh auth login
git clone --branch renoir --single-branch https://github.com/wannqn/darwin-renoir.git
cd darwin-renoir
python3 recovery/restore.py --build-inputs
```

The script verifies SHA256 for seven release assets, restores the original packfs
images and password-free kernel/root payloads, native Renoir firmware and build
tools, and relocates SDK symlinks. **It does not produce the APFS boot images.**
The originals remain source and rollback artifacts; do not delete or overwrite
`userland/system.packfs` or either archived share payload.

Before the default boot, rebuild the current kernel/Mesa/userland and convert the
preserved inputs into genuine APFS containers:

```sh
# apply.sh is for a missing source tree only; existing sources must match this branch.
test -d xnu-src/xnu-8796.121.2 || bash xnu/apply.sh
bash tools/mk-ath11k.sh
./xnu-build.sh -j6
bash tools/mk-mesa.sh
SHARE=1 GL=1 CHECK=1 bash userland/build.sh
SKIP_UEFI=1 bash tools/update-prebuilt.sh
```

Without extracted Apple inputs, `build.sh` extracts the archived share payload's
small root, preserves its selected iOS jobs and ownership manifest, overlays
current programs/libraries, and builds `userland/root.apfs`. It converts preserved
`system.packfs` into `system.apfs`, replacing the old `/sbin/launchd` stage0 with
the rebuilt APFS-mounting program. The old stage0 cannot mount APFS and must not be
carried over unchanged. `JOBS`, `REST` and `OSLOG` selection changes require the
original extracted Apple job inputs; do not use `REST=1` on the archive-backed path.
`CHECK=1` requires host C build tools, OpenSSL/zlib development files and Git;
legacy extraction also needs LZ4/Zstd libraries. The checker fetches pinned
`linux-apfs/apfsprogs` and independently reads the images using the kernel's reader.
Old prebuilt init/stage0 binaries without matching APFS source provenance are rejected.
`SKIP_UEFI=1` refreshes only kernel/userland and preserves loader/board artifacts.

Passwords, SSH keys and access tokens are excluded by `SHARE=1`. Configure Wi-Fi
manually in iOS. The boot script prompts for the handset's Android device Wi-Fi
MAC, validates it and replaces any archived address before contacting the phone.

Put the phone in **stock fastboot** and run:

```sh
python3 recovery/boot.py
```

Enter your device MAC from Android's About phone/Status page when asked. An
address can be entered **with or without colons** (`AABBCCDDEEFF` or
`AA:BB:CC:DD:EE:FF`); the prompt explicitly says colons are optional. An
invalid address is rejected and prompted again; cancelling or closing input
stops before USB access. To skip the prompt, pass `--wifi-mac AA:BB:CC:DD:EE:FF`.
This is the default APFS boot command. It uses the rebuilt kernel in
`prebuilt/mach.development.bcm2837`, `userland/system.apfs` as `/`, and
`userland/root.apfs` as `/redwood`, with writable ramfs on `/private/var`.
It starts eight cores (`cpus=8`). A freshly rebuilt kernel can be selected with
`--kernel PATH`; this does not remove the requirement for both APFS images.
Add `--last-phone-good` instead for the explicit legacy path: archived earlier
kernel/root **and preserved `userland/system.packfs`**, with its original boot
arguments. That option does not need APFS images. Never pair the old kernel/root
with APFS containers or substitute a new APFS kernel into the old packfs root.
`--boot-arg NAME=VALUE` (repeatable) adds or replaces one kernel boot argument
for that boot only, e.g. `--boot-arg touch_lat=1 --boot-arg touchscreen=0` for
the latency measurement in [the GPU notes](../docs/renoir-gpu-investigation.md).

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

For a new computer without recovery assets, use the complete
[source build guide](BUILD-FROM-SOURCE.md). Board firmware is now tracked in Git;
see [vendor input inventory](FIRMWARE.md).

Build inputs include the Theos SDK/toolchain, XNU host tools/libraries and QEMU.
Install Linux packages as needed: clang, lld, llvm, make, cc/c++, git, curl, Python,
7z, flex, bison, autoconf, automake, nasm, pkg-config, OpenSSL, zlib, LZ4 and Zstd
(including development files). Use the WSL Linux filesystem.

```sh
# Fresh kernel source tree only:
bash xnu/apply.sh
./xnu-build.sh -j6
```

With original Apple inputs (`bash ios165/fetch.sh`), userland can be built directly
from the extraction, including a new job selection:

```sh
bash tools/mk-mesa.sh
GL=1 REST=1 WIFID=1 SHARE=1 CHECK=1 RC_JOBS=rc.jobs.renoir bash userland/build.sh
SKIP_UEFI=1 bash tools/update-prebuilt.sh
QEMU_RAM_GB=6 CMDLINE=-v bash qemu/run-ios.sh 600
```

The archive-backed workflow above needs no IPSW download. The current APFS
validation produced a 2,495,967,232-byte system container and a 14,397,440-byte root
container. `apfsck` found both clean; the independent kernel-reader comparison
matched all 61,249 system entries and 484 root entries. QEMU with the corrected
generic mount-argument registration confirmed read-only APFS on `/` and
`/redwood`, writable ramfs on `/private/var`, and successful var write/read/unlink.
Subsequent physical Renoir RAM boot, after Android/SurfaceFlinger initialization
and a fresh resident-loader start, confirmed the same mounts in
`renoir-apfs-mesa26-cold.log`: `/` APFS flags `0x4005001`, `/redwood` APFS
`0x4001001`, `/private/var` ramfs `0x4001000`. Directory creation and explicit var
write/read/unlink passed, and init reported **40 checks, 0 failed**. GPU step 21
succeeded; CoreAnimation used hardware OpenGL ES 3.2, Mesa 26.2.5, FD642 and drew
frames. A captured home screen retained icons, text and wallpaper, with two
partly unloaded widgets. This verifies the observed APFS/hardware-rendering boot
path, not a performance/tearing improvement or a complete system regression.
Earlier packfs Wi-Fi/audio/camera results are not new regressions of those drivers.

Before deleting local work, verify both branches and all seven assets plus
SHA256SUMS. Keep access to your GitHub account. Old logs/RAW captures, Apple IPSW
source inputs and build caches are not archived.

## Sileo and a root shell over Wi-Fi

`tools/mk-jb.sh` fetches the rootless Procursus bootstrap with Sileo, ElleKit and OpenSSH into
`jb/` (not in the repository). `userland/build.sh` then puts it into `system.apfs` as `/jb` (from
`system.packfs` with `convert-packfs.py --add/--link`), and `init` grafts it onto `/var/jb` in RAM
at every boot. The normal job list (`userland/rc.jobs.renoir`) runs the bootstrap's `prep.sh` and
starts the prefix's `sshd`: root by key only, no passwords.

Keys stay on this computer: `ssh/authorized_keys` (the public half of your client key) and
`ssh/ssh_host_ed25519_key` (`ssh/` is ignored by git). A build without `SHARE=1` puts them on the
data volume; never pass such an image on. After joining Wi-Fi in Settings:

```sh
ssh -i ~/.ssh/renoir_ed25519 root@<the phone's address>
```

Everything under `/var` is in RAM: packages installed with Sileo or apt and the Wi-Fi password
are gone after the next boot.

## Historical packfs Wi-Fi startup correction

The source now allows Renoir Wi-Fi to start without `fw/network`, which is
deliberately omitted from `SHARE=1` images. Previously this missing optional
credential file prevented radio startup, blocking scanning and manual join in
Settings. Firmware and the phone's `wifi_mac` remain required.

The Wi-Fi correction remains in current source. The earlier phone-validated kernel
is preserved at `recovery/assets/renoir-wifi-fixed.kernel`; see
[build and validation notes](wifi-fix-validation.md). On a second physical Renoir,
that earlier packfs build started the radio and showed 2.4 GHz and 5 GHz networks.
Open-network and WPA2 joining with Safari internet access were user-confirmed.
Those Wi-Fi results remain historical; the current physical APFS/Mesa boot proof
above is not a repeated Wi-Fi/internet regression.
The current default helper substitutes **both** the rebuilt kernel and APFS small
root into a temporary copy of the archived payload. Original release checksums
and the explicit `--last-phone-good` fallback stay intact.

After completing the APFS rebuild/conversion above, return the phone to stock fastboot:

```sh
python3 recovery/boot.py
```

Wait for iOS, open Settings → Wi-Fi, enable the switch, select a network and
enter its password. Check that the switch stays on, networks appear and Safari
can load a page. Gateway and DNS should be supplied by DHCP after joining.
If it fails, collect the live RAM log before rebooting:

```sh
fastboot -s xnuloader oem log
fastboot -s xnuloader get_staged recovery/assets/wifi-phone.log
```

If boot stops at the Silicium logo, read the terminal first. A failed
`stage ... system.apfs` means the kernel was never uploaded or started;
the logo alone does not diagnose a kernel hang. `fastboot devices` should list
`xnuloader` while the resident loader is waiting. The boot helper now streams
upload output and reports captured fastboot errors. The system upload allows
up to 900 seconds, but an immediate fastboot failure still needs its actual
error message investigated. Do not attempt `oem run` after a failed upload.

After preparing both APFS images, a rebuilt kernel can be selected with your
own handset's Wi-Fi address (replace the example):

```sh
# Existing kernel sources must already match the current APFS branch.
bash tools/mk-ath11k.sh
./xnu-build.sh -j6
python3 recovery/boot.py --wifi-mac 02:11:22:33:44:55 \
  --kernel xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
```

Run `xnu/apply.sh` only when the extracted XNU source directory does not already
exist. Obtain the address while Android Wi-Fi is enabled, from the device Wi-Fi
MAC in Settings or `adb shell cat /sys/class/net/wlan0/address` (some Android
builds require root for that read). Use the device/interface address, rather
than a router-specific randomized address. The default helper replaces the kernel,
small root, requested MAC, timestamp and CPU count in a temporary payload.
The explicit legacy option keeps its archived kernel/root and CPU count together.
No archived asset or phone partition is modified.
