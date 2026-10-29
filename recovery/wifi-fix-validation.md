# Renoir Wi-Fi recovery fix — 2026-10-28

The current source and prebuilt kernel restore Wi-Fi on a second Renoir handset:
2.4/5 GHz scanning, open/WPA2 joins and Safari internet access are phone-confirmed.
The fixes remove a saved-credentials startup dependency, reserve firmware DMA
memory before userland fragments RAM, isolate management replies by exchange,
and implement explicit open-network joining. The normal boot helper selects
this kernel and prompts for the handset's MAC, accepting optional colons.

Validation includes 18 recovery/Wi-Fi host test scripts, 36 prebuilt checksums,
release root/system checksums, and resident-loader phone tests. Complete cold
RAM-boot regression of the final combination and other integrated hardware
features remain pending. The chronological evidence and exact hashes follow.

## Confirmed failure in the release

The local offline bundle's `ios-payload.bin` matches release asset
`renoir-ios-share.bin` (SHA256
`548859eebf8c27d4ecb4710e330d59e0313780ffce86b1fe0d08e9e17b31fbaf`).
Its kernel contains the Renoir startup refusal for a missing network file.
Its root packfs omits `/fw/network`, as required for a password-free image,
but includes Wi-Fi firmware and `com.apple.wifid.plist`.

Remove the optional network-file prerequisite from `renoir_wifi_begin`.
The existing `join_given` already handles its absence by leaving the station
available for manual join. Hardware, firmware and station-address checks remain.

The recovery helper requires a device MAC (prompted or supplied with `--wifi-mac`)
and supports `--kernel`, validates inputs
before interacting with the phone and recalculates the XNUP container length
after edits. Archived input assets remain unchanged. A MAC override avoids
reusing the original handset's address; it is separate from the confirmed
missing-network-file startup failure.

## Local build

Fresh application of the full patch to pinned Apple XNU `c54f35ca` succeeded.
Pinned ath11k/LinuxKPI inputs were built from source; ath11k has zero generated
function stubs. XNU build completed with exit 0 using Fedora clang 22.1.8,
the pinned iPhoneOS 16.5 SDK, Theos cctools and locally built XNU dependencies.
Compiler and host-tool packages were extracted inside ignored `build-tools/`.
`XNU_CLANG_DIR` allows selecting this local compiler without a system install.

Build commands after setup:

```sh
source build-tools/env.sh
bash tools/mk-ath11k.sh
./xnu-build.sh -j6 DSYMUTIL="$PWD/build-tools/host-root/usr/bin/dsymutil"
```

The linked unstripped kernel contains `_ath11k_core_init`. The final ARM64
Mach-O contains the corrected refusal diagnostic and lacks the old diagnostic.

| Local artifact | Bytes | SHA256 |
| --- | ---: | --- |
| `recovery/assets/renoir-wifi-fixed.kernel` | 15645432 | `2ba66e7ed92be213a371027e45a553aba9cfd0f3e22b4d67ff14c804d1e6c21b` |
| `recovery/assets/renoir-wifi-fixed.bin` | 56949928 | `6756a521f237c4b3d90eb4c5887cf6778a1dc4da915487a3f81d0922db386b05` |

The standalone payload uses epoch 0 as a placeholder. Use the recovery helper
with `--kernel` for testing; it refreshes time and applies the requested MAC.
The root and system images match their original release SHA256 values; early
GPU firmware remains uncompressed and matches the tracked firmware inputs.

## Verification

Passed: four recovery-container tests, actual credential-free startup gate,
Wi-Fi option defaults, DMA pool reservation, station fallback, Apple80211
capability ABI and group-key handling. Existing sanitizer tests ran with
`ASAN_OPTIONS=detect_leaks=0` because LeakSanitizer cannot operate under this
environment's ptrace restriction; address/undefined checks remained enabled.

Logs: `build-tools/xnu-setup.log`, `ath11k-build.log`, `xnu-build.log`,
`wifi-host-tests.log` and `qemu-wifi-fix.log` under `build-tools/`.

Initial kernel (before the subsequent BHI reservation correction):
QEMU 10.2.2, 6 GiB, one TCG CPU, restored release root/system, rebuilt kernel,
`-v wifi=1`: SpringBoard, wifid and the window server started. The guest returned
normally after its 420-second timer (`kernel returned`, `returned 647523 0`).
The host wrapper later exited 124 at its expected 460-second timeout while
replaying the log. No observed kernel panic, usertrap or userabort. Screenshots
showed the Apple logo followed by a black screen; a home-screen/UI pass is not
claimed. Physical Wi-Fi correctly stayed disabled on the QEMU board. This run
does not establish radio, scanning, DHCP or internet functionality.

The actual prepared phone payload was checked for a byte-identical root image,
the corrected kernel, a valid container length, successful MAC/time rewriting
and size below the resident loader's upload limit. Checksums are also saved in
`recovery/assets/wifi-fix-SHA256SUMS`.

## Physical Renoir validation and second correction

An initial phone attempt failed during the system-image USB upload, before the
kernel was sent. Linux recorded the resident loader disconnecting. A later
retry succeeded: system image uploaded in 96.627 seconds and kernel/root in
1.965 seconds. The launcher now exposes upload output and driver errors instead
of hiding them behind a Python traceback; timeout allowances match the offline
launcher (900 seconds for system, 180 for kernel/root). No host USB power or
policy settings were changed.

The first corrected kernel booted iOS and passed the optional-credentials gate,
but reported `BHI has no contiguous firmware buffer`. The existing 80 MiB data
pool reservation had succeeded; the separate firmware/control/target buffer was
still being allocated after userland fragmented RAM.

Reserve that exact buffer during normal Renoir Wi-Fi initialization, before
userland starts. For this firmware it is 13344 KiB. Keep it outside the session
structure reset by `renoir_bhi_host`. Preparation consumes it once for an exact
size match, validates physical continuity and installs the original SMMU/DMA
mapping. Other sizes use the existing allocation path. Cleanup retains its
existing reset, mapping restoration and allocation ownership rules. No device
mapping or DMA is performed by the reservation itself.

Passed the real BHI/BHIE failure/rollback suite and a new host test for bounded,
idempotent reservation, exact-size consumption despite later allocation failure
and fallback behavior. The second kernel built with exit 0. Source changes were
copied into the existing extracted kernel tree before the incremental rebuild.

The first session returned normally through `oem stop`. The second payload was
staged and run from the resident loader, reusing the system RAM image. Phone log
confirms early reservation and consumption, successful signed firmware transfer
(EE 2), `ath11k PCIe start result 0 transport failed 0` and station publication
to iOS with no saved network file. Scans returned 13 access points across 2.4 GHz
and 5 GHz; Settings received results. The user confirmed that networks appear,
including 5 GHz. Association/internet validation is pending.

Evidence: ignored `recovery/assets/wifi-phone-{first,live,v1-returned,bhi,current}.log`.
This second build is preserved as `renoir-wifi-bhi.*`, and the first build as
`renoir-wifi-v1.*`. Neither build is a new published release. Later test builds
and the final artifact selection are recorded below.

## Management response correction and address setup investigation

After scanning was confirmed, WPA2 joins failed with authentication accepted
but association reported refused with status 0, AID 0 and no response elements.
The station used one unfiltered reply slot for authentication and association;
a delayed/duplicate authentication response could terminate the association wait.

`answer_begin` now arms an expected management response subtype under the
receive-side lock. Replies from another phase are ignored, association metadata
is published atomically with its result, and delayed replies cannot override a
disconnect. A host test exercises the actual receive code with reordered replies,
proper association/rejection, malformed frames, wrong peers and disconnects.
The driver and third kernel rebuilt successfully.

On the phone this correction passed authentication, association (AID 1), the
WPA2 four-way handshake and pairwise/group key installation. The kernel reported
the network joined. iOS then acquired only a link-local IPv4 address; HTTPS/DNS
failed and Settings kept its spinner. This is not an internet pass.
Evidence: ignored `wifi-phone-management-live.log` and `wifi-phone-dhcp-failed.log`
under `recovery/assets/`. Group frames arrived, but the recorded failed connection
had zero unicast receive frames. DHCP/data-path diagnosis remains in progress.

The fourth candidate adds opt-in `wifi_trace=1` bounded Ethernet/IP/UDP header
diagnostics, with no names, keys or application content. The trace is off in
normal boots. Its parser passed sanitizer tests for short/invalid headers,
fragment handling, DHCP metadata and output limits. Both driver and kernel build.
Password-free networks remain explicitly unsupported by the preexisting station
join implementation; their rejection must not be mistaken for a WPA2 key failure.

The fourth phone trace confirmed repeated DHCP requests (UDP 68→67, BOOTP
request) and no offers, while multicast IPv4 traffic arrived. Other devices
work on the tested routers, according to the user. Host packet capture was
unavailable without administrator authentication; no host permissions were changed.

## Open-network support and fifth phone build

The fifth build admits explicitly selected open networks through the existing
authentication/association path, omits their RSN element and privacy bit, skips
the WPA key exchange/key installation, and authorizes the associated peer.
Protected access points are rejected when requested as open; WPA2 continues to
require its original security negotiation. Host tests execute the actual
security-selection and RSN-emission helpers for open, WPA2/CCMP, WPA2/TKIP group,
and protected-network downgrade refusal.

Opt-in header diagnostics additionally validate IPv4/UDP checksums and describe
the DHCP message type, station-address matching and broadcast-request bit.
Independent valid/corrupt packet fixtures and short/malformed headers pass
ASan/UBSan tests. No packet content, SSID, password or key is added to these traces.

The fifth driver/kernel build passed. It was loaded through the resident RAM
loader after the preceding kernel returned. The user confirmed the password-free
network connects and Safari works. This establishes open-network internet access
on this handset. The user then confirmed WPA2 joining and Safari internet access
on the same build. Final log records accepted authentication/association,
successful key installation with both 32-byte and 16-byte group-key lengths
across the attempts, and network-joined events. No observed kernel panic.
Evidence: `recovery/assets/wifi-phone-final-success.log` and the user's explicit
open/WPA2 Safari confirmations. Do not infer an internet pass for every scanned
access point or every security configuration from these tests. Earlier WPA2
DHCP failures remain recorded above; no separate universal DHCP fix is claimed.

The current `renoir-wifi-fixed.*` artifacts contain this open-capable fifth build.
Its normal payload leaves packet tracing disabled. Earlier test kernels remain
preserved under `renoir-wifi-v1`, `renoir-wifi-bhi`, `renoir-wifi-management` and
`renoir-wifi-trace`; the handset-specific fifth test is `renoir-wifi-open.bin`.
Source/build logs and phone logs remain local. The phone remains running in RAM.
The final combination has been validated through resident RAM reloads, not a
fresh complete stock-fastboot-to-iOS run. The initial kernel did pass that full
upload/boot path; the final kernel uses the same archived root/system images.

## Boot-path cleanup

The exact fifth phone-tested kernel is promoted to the tracked
`prebuilt/mach.development.bcm2837`, with its checksum updated in
`prebuilt/SHA256SUMS`. The original tracked kernel was preserved locally as
`recovery/assets/pre-wifi-original-prebuilt.kernel` before replacement. Archived
release assets remain byte-identical. No old logs, test payloads or build inputs
were deleted.

Normal `recovery/boot.py` boots now select that current prebuilt kernel. A valid
device MAC is mandatory: without `--wifi-mac`, the script prompts interactively.
Saved files and the archived handset's address cannot bypass the prompt.
Invalid answers are retried; EOF or cancellation stops before USB access.
`--kernel` and `--last-phone-good` are mutually
exclusive explicit overrides. Device model checks use an exact value match.

Fourteen isolated end-to-end CLI tests exercise the actual launcher with a fake
fastboot transport: required/invalid MAC, current default kernel, custom kernel,
explicit fallback, conflicting overrides, similar-but-wrong model, refusal to
overwrite a resident loader, and failure before kernel execution when upload
fails, plus interactive entry, retry after invalid answers and EOF after an
invalid answer, plus compact MAC input through both the prompt and command-line
option. Colons are explicitly optional; compact input is normalized to the
colon-separated boot argument expected by the kernel. These tests do not
interact with the physical phone. Python remains the
canonical launcher; no shell wrapper is required.

Final cleanup checks: all 18 recovery/Wi-Fi host test scripts passed; all 36
entries in `prebuilt/SHA256SUMS` matched; restored root/system images matched
their release checksums; and the default prebuilt was byte-identical to the
fifth phone-tested kernel. Documentation now uses the required-MAC command.
The physical phone was left running throughout these launcher/cleanup checks.

Publication scope: source, tests, documentation and the tested prebuilt kernel
on the private GitHub `wannqn/darwin-renoir` backup's `renoir` branch. Release
assets remain unchanged. Runtime logs, personal network configuration and build
caches stay ignored. No phone partition operation was performed.

## Integration of the 90 Hz updates (2026-10-29)

Fast-forwarded the private GitHub backup through `2aff3b5`, including driver
cleanup, the `renoir.patch` rename, Adreno/display changes and the replacement
90 Hz prebuilt kernel. The Wi-Fi source fixes and interactive MAC prompt remain
in place. The recovery payload now also receives the incoming CPU, touch and
framebuffer boot options.

The current default kernel is the incoming prebuilt, SHA256
`bc75167eaa58c1343f56db1b36e467fbfa8580a294e290d2dac4eb58355c4327`.
The earlier Wi-Fi-tested kernel (`2ba66e7e…`) is preserved locally in the
pre-integration Git stash and ignored recovery assets. Earlier hardware results
above apply to that earlier kernel; the incoming 90 Hz kernel has not been
validated on this handset in this integration session. The checksum manifest
was corrected to match the incoming binary. No phone operation or release
asset replacement was performed.

The original GitLab remote could not be checked without credentials. This
integration includes the four new commits available on `origin/renoir`.

Integration validation: all 18 recovery/Wi-Fi host test scripts and the renamed
patch statusbar test passed (19 scripts total). The payload suite now has six
tests, including repeated preparation of the incoming boot options. All 36
prebuilt checksum entries match. These are host checks, not hardware validation
of the incoming kernel.

## Combined source rebuild after connection regression (2026-10-29)

The user reported that Wi-Fi did not connect with the incoming 90 Hz prebuilt.
A fresh Apple XNU tree was created from the locally available pinned tag, then
the complete current `xnu/renoir.patch` and `xnu/files` were applied. The old
working source tree was preserved. Both ath11k and XNU were rebuilt from current
sources, rather than reusing the incoming binary or the older kernel objects.

```sh
source build-tools/env.sh
export XNU_SRC="$PWD/xnu-src/renoir-integrated-20261029"
# Initial setup used xnu/apply.sh with the local pinned Apple source as XNU_URL.
bash tools/mk-ath11k.sh
./xnu-build.sh -j6 DSYMUTIL="$PWD/build-tools/host-root/usr/bin/dsymutil"
```

Both builds exited successfully. Ath11k reports zero generated function stubs;
the linked kernel contains `_ath11k_core_init` and `_lx_station_join`. The new
prebuilt combines the pulled display/GPU changes with the existing Wi-Fi source
fixes. The canonical boot helper already loads this prebuilt by default.

- Kernel: 15,440,112 bytes, SHA256
  `a2ed0c6dd1456c09d339da3d8d5b55d3c39f56f464888dbd9e3ab9986bf26af3`.
- Local generic SHARE payload: 56,744,632 bytes, SHA256
  `9a1154c3af7154dc39d6baf3db76ed6cba018a5629de2032ef0687eed089e0c0`.
- Build logs: `build-tools/ath11k-integrated-build.log` and
  `build-tools/xnu-integrated-build.log` (ignored).

All 19 selected recovery/Wi-Fi/statusbar host test scripts passed, and all 36
prebuilt checksum entries match. The incoming 90 Hz prebuilt is preserved in
ignored `recovery/assets/incoming-90hz-2aff3b5.kernel`; the earlier Wi-Fi-tested
kernel remains preserved too. Archived SHARE root/system images are unchanged;
userland was not rebuilt. No phone was available in fastboot during these
checks, so Wi-Fi association and Safari on this combined kernel still require
hardware validation. No partition was written and no release asset replaced.

Subsequent hardware check: a full cold RAM boot completed successfully after
the phone became available. The system upload took 97.126 seconds and the
kernel/root upload took 1.963 seconds. The live log confirms early Wi-Fi buffer
reservation, radio initialization and scanning on both 2.4 GHz and 5 GHz, with
no panic observed in the collected log. WPA2 association and Safari results
are still pending user confirmation. Evidence stays local in ignored
`recovery/assets/wifi-integrated-first.log` and `wifi-integrated-live.log`.

## Display regression rollback (2026-10-29)

The user confirmed Wi-Fi and Safari work on the combined rebuild, then reported
severe visual artifacts during Bluetooth investigation and requested abort.
Bluetooth work was stopped. The default prebuilt was restored to the earlier
phone-tested Wi-Fi kernel, SHA256
`2ba66e7ed92be213a371027e45a553aba9cfd0f3e22b4d67ff14c804d1e6c21b`.
The incoming forced `cpus=8`, `touch_lat=1` and `fb_filter=0` edits were removed
from the recovery payload helper: it again preserves the archived boot options.
The normal SHARE root and earlier kernel were RAM-booted again, with no
Bluetooth probe job. The newer kernels and ignored diagnostic images are
preserved locally. Source changes remain in Git for later investigation; this
rollback changes the default binary and boot options, not repository history.

Payload and boot-helper tests pass; all 36 prebuilt checksums match. Visual
recovery on the restored build still requires user confirmation. Bluetooth
remains unsupported; no functional Bluetooth fix was made.
