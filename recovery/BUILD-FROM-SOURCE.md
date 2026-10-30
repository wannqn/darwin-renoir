# Build Renoir without recovery releases

Run these commands in Bash on x86-64 Linux or WSL, inside its Linux filesystem.
This path does not use our GitHub recovery release. It downloads Apple's original
iOS files and third-party build tools. macOS itself is not needed: setup.sh fetches
the macOS 13.3 SDK headers needed for XNU. Allow at least 40 GB free disk space.

## 1. Clone and install host tools

Arch Linux / the WSL distribution used for this port:

```sh
sudo pacman -S --needed base-devel git github-cli curl clang lld llvm python \
  python-pip python-virtualenv perl xz p7zip flex bison m4 autoconf automake \
  nasm meson ninja pkgconf openssl zlib lz4 zstd android-tools aarch64-linux-gnu-gcc \
  qemu-system-aarch64 edk2-aarch64
gh auth login
gh auth setup-git
git clone --branch renoir --single-branch https://github.com/wannqn/darwin-renoir.git
cd darwin-renoir
```

Use 7-Zip 23 or newer with APFS support (`7z i`); some distributions call the
package `7zip` instead of `p7zip`. Ordinary Linux packages are prerequisites;
their names may differ between distributions. Keep the terminal in this clone
unless a command below explicitly changes directory.

## 2. Install the cross compiler and SDKs

Install Theos using its [official Linux installer](https://theos.dev/docs/installation-linux):

```sh
curl -fL https://raw.githubusercontent.com/theos/theos/master/bin/install-theos -o /tmp/install-theos
bash /tmp/install-theos
export THEOS="$HOME/theos"
```

The build needs exactly `iPhoneOS16.5.sdk`, not just the installer's newest SDK.
If missing, copy it from the pinned SDK source used for this workspace:

```sh
if [ ! -d "$THEOS/sdks/iPhoneOS16.5.sdk" ]; then
  git clone --no-checkout https://github.com/theos/sdks.git build-sdk-inputs
  git -C build-sdk-inputs checkout 0222fd5413cf4b9af096f37b4621afa2688572f7
  mkdir -p "$THEOS/sdks"
  cp -a build-sdk-inputs/iPhoneOS16.5.sdk "$THEOS/sdks/"
fi
test -x "$THEOS/toolchain/linux/iphone/bin/ld"
test -d "$THEOS/sdks/iPhoneOS16.5.sdk/usr/include"
bash xnu/apply.sh
bash xnu-deps/setup.sh
```

`apply.sh` fetches Apple XNU and applies our kernel changes. Run it once in a fresh
clone; it deliberately refuses an existing kernel directory. `setup.sh` fetches
and builds host tools/libraries and downloads macOS SDK headers automatically.

## 3. Download iOS and build the kernel/userland

```sh
bash ios165/fetch.sh
bash tools/mk-ath11k.sh
./xnu-build.sh -j6
bash xnuloader/build.sh
bash xnuloader/build.sh renoir
bash tools/mk-mesa.sh
GL=1 REST=1 WIFID=1 SHARE=1 CHECK=1 RC_JOBS=rc.jobs.renoir bash userland/build.sh
```

`fetch.sh` retrieves the iPhone X iOS 16.5 (20F66) root filesystem and OS cryptex
directly from Apple's IPSW CDN. It extracts the selected files and dyld cache;
there is no macOS installation or recovery-release download in this step.
The build creates genuine `userland/system.apfs` and `userland/root.apfs` containers.
The resident system container becomes read-only `/` (`/dev/md0`); its rebuilt
stage0 mounts the small container read-only on `/redwood` (`/dev/md1`).
Init keeps `/private/var` writable in ramfs. `CHECK=1` runs pinned `apfsck` and
independently compares every entry with the kernel's host-built APFS reader.
This requires host OpenSSL/zlib development files and may fetch `apfsprogs`.
Only RAM-backed APFS boot is supported; no phone storage is formatted or written.
Renoir GPU, Wi-Fi, ADSP/speaker and camera inputs are already in the clone
([inventory](FIRMWARE.md)); userland packages them into the correct board paths.
Do not set `ADSP=1` with `GL=1`: the build puts ADSP in the large system image.

If using restored recovery releases instead of original Apple extraction inputs,
follow [the archive-backed APFS conversion workflow](README.md). Restored
`system.packfs` and share payloads are preserved source artifacts, not inputs to
the default APFS boot helper. The build replaces the old packfs stage0 during
conversion. Do not set `REST=1` on that path: it retains the archive's selected
jobs until original job inputs are available. `--last-phone-good` is a separate
legacy pairing of archived kernel/root with preserved `system.packfs`.

## 4. Build our Project Silicium

```sh
git clone --branch silicium-renoir --single-branch --recursive \
  https://github.com/wannqn/darwin-renoir.git Mu-Silicium
python3 Mu-Silicium/Recovery/prepare.py
python3 -m venv build-tools/uefi-venv
build-tools/uefi-venv/bin/pip install -r Mu-Silicium/pip-requirements.txt
(
  cd Mu-Silicium
  PATH="$PWD/../build-tools/uefi-venv/bin:$PATH" \
    CLANGPDB_AARCH64_PREFIX=aarch64-linux-gnu- python3 build_uefi.py -d renoir -r RELEASE
)
python3 xnuloader/mkpayload.py -o resident-payload.bin \
  loader.efi=xnuloader/loader-renoir.efi --usb
python3 mkxnuimg.py --device renoir -p resident-payload.bin -o xnu-renoir-usb.img
```

Use this custom branch, not an unpatched stock Silicium checkout.
`Recovery/prepare.py` restores the saved Mu_Basecore patches and Renoir marker.
The generated boot image contains BootShim, our UEFI and the resident XNU loader.

## 5. Test in QEMU

```sh
set -o pipefail
CMDLINE="-v" bash qemu/run-ios.sh 600 2>&1 | tee boot.log
```

The 600-second run is time-limited and its timeout exit is expected. Inspect the
console for actual `apfs` read-only mounts on `/` and `/redwood`, `ramfs` on
`/private/var`, and a successful var write/read/unlink check. Those filesystem
checks have passed in QEMU; QEMU alone cannot validate phone drivers. A subsequent
physical Renoir run after Android/SurfaceFlinger initialization and a fresh
resident-loader start confirmed APFS `/` and `/redwood`, writable ramfs var,
directory creation, and **40 checks, 0 failed**. GPU step 21 and CoreAnimation
hardware OpenGL ES 3.2 / Mesa 26.2.5 / FD642 rendering also succeeded; the captured
home screen had intact icons, text and wallpaper, with two partly unloaded widgets.
This is observed boot/rendering evidence, not a performance/tearing improvement
or full Wi-Fi/audio/camera/system regression.
If your distribution installs AArch64 UEFI elsewhere, set `QEMU_EFI` and
`QEMU_VARS` as described in `qemu/run.sh`.

## 6. Boot the phone from RAM

Use Linux `adb`/`fastboot` with USB access to exactly one Renoir. For WSL, pass the
USB device through to WSL first. These examples use Linux paths and binaries;
do not pass them unchanged to Windows fastboot.exe.
While Android is running, save this phone's Wi-Fi address with Wi-Fi enabled:

```sh
mkdir -p fw-wifi
adb shell su -c 'cat /sys/class/net/wlan0/address' | tr -d '\r' > fw-wifi/mac
adb reboot bootloader
fastboot getvar product  # must report renoir
fastboot boot xnu-renoir-usb.img
```

Wait until `fastboot devices` reports the resident `xnuloader`, then:

```sh
fastboot -s xnuloader getvar board  # must report renoir
fastboot -s xnuloader oem ramdisk
fastboot -s xnuloader stage userland/system.apfs
python3 xnuloader/mkpayload.py -o run-payload.bin \
  kernel=xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837 \
  ramdisk=userland/root.apfs \
  --cmdline "-v loader_return_after=0 epoch=$(date +%s) haptic=5 bootcpu=7 cpus=4 cpufreq=1 touchscreen=1 buttons=1 gpu=1 wifi=1 wifi_mac=$(cat fw-wifi/mac) wifi_quiet=1 wifi_loud=1 adsp=1 battmgr=1 speaker_probe=2 renoir_afe_probe=1 sound=4 sound_below=160 sound_gain=0 cam=5 cam_stream_test=1 cam_sensor=wide cam_after=2 cam_keep_mb=32"
fastboot -s xnuloader stage run-payload.bin
fastboot -s xnuloader oem run
```

This uses the boot arguments preserved in the current recovery snapshot, without
a kernel session timer. Select Wi-Fi and enter its password in Settings.
Rebooting returns to Android; RAM-session data is lost. Never flash, erase,
unlock or repartition. Persistent-storage APFS boot and the failed 90 Hz experiment
are not enabled. This complete fresh-download workflow has been checked against
the scripts, but has not yet been run end-to-end on a newly installed computer;
the physical boot evidence above used the restored-input build, not that fresh-install workflow.
