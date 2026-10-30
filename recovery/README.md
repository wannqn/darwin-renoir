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
and enter its password in iOS. The boot script prompts for your handset's Android
device Wi-Fi MAC. It validates your answer and replaces any address in the
archived payload before contacting the phone.

Put the phone in **stock fastboot** and run:

```sh
python3 recovery/boot.py
```

Enter your device MAC from Android's About phone/Status page when asked. An
address can be entered **with or without colons** (`AABBCCDDEEFF` or
`AA:BB:CC:DD:EE:FF`); the prompt explicitly says colons are optional. An
invalid address is rejected and prompted again; cancelling or closing input
stops before USB access. To skip the prompt, pass `--wifi-mac AA:BB:CC:DD:EE:FF`.
This is the canonical boot command. It uses the current tested kernel in
`prebuilt/mach.development.bcm2837` and starts eight cores (`cpus=8`: the boot
CPU plus seven secondary cores). A freshly rebuilt kernel can be
selected with `--kernel PATH`. Add `--last-phone-good` instead to explicitly
select the earlier archived kernel/root and its original boot arguments.

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

The Wi-Fi kernel is phone-tested on a second Renoir, with open/WPA2 joining and
Safari confirmed. Other integrated features and a complete cold RAM boot of the
final combination have not been regressed. QEMU does not validate physical Renoir
drivers. The earlier payload is preserved as a password-free fallback.

Before deleting local work, verify both branches and all seven assets plus
SHA256SUMS. Keep access to your GitHub account. Old logs/RAW captures, Apple IPSW
source inputs and build caches are not archived.

## Wi-Fi startup correction

The source now allows Renoir Wi-Fi to start without `fw/network`, which is
deliberately omitted from `SHARE=1` images. Previously this missing optional
credential file prevented radio startup, blocking scanning and manual join in
Settings. Firmware and the phone's `wifi_mac` remain required.

The corrected kernel is included at `prebuilt/mach.development.bcm2837` and is
the boot helper's default. Archived release payloads retain their original
checksums; the helper substitutes the current kernel at boot. A local copy is
also preserved at `recovery/assets/renoir-wifi-fixed.kernel`; see
[build and validation notes](wifi-fix-validation.md). On a second physical Renoir,
the corrected build starts the radio and shows both 2.4 GHz and 5 GHz networks.
Open-network and WPA2 joining with Safari internet access are user-confirmed on
this build. Details and the earlier DHCP test failures are recorded in the
validation notes. A complete cold RAM-boot regression of the final combination
has not yet been repeated; the phone test used the resident loader.

Return the phone to stock fastboot, run the script and enter your device MAC:

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
`stage ... system.packfs` means the kernel was never uploaded or started;
the logo alone does not diagnose a kernel hang. `fastboot devices` should list
`xnuloader` while the resident loader is waiting. The boot helper now streams
upload output and reports captured fastboot errors. The system upload allows
up to 900 seconds, but an immediate fastboot failure still needs its actual
error message investigated. Do not attempt `oem run` after a failed upload.

With restored build inputs, build the corrected kernel and boot it with your
own handset's Wi-Fi address (replace the example):

```sh
bash xnu/apply.sh
bash tools/mk-ath11k.sh
./xnu-build.sh -j6
python3 recovery/boot.py --wifi-mac 02:11:22:33:44:55 \
  --kernel xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
```

Run `xnu/apply.sh` only when the extracted XNU source directory does not already
exist. Obtain the address while Android Wi-Fi is enabled, from the device Wi-Fi
MAC in Settings or `adb shell cat /sys/class/net/wlan0/address` (some Android
builds require root for that read). Use the device/interface address, rather
than a router-specific randomized address. The helper replaces the kernel,
requested MAC, timestamp and (except for `--last-phone-good`) CPU count in a
temporary payload; archived assets stay intact.
