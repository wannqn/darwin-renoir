# Renoir Bluetooth bring-up status

Bluetooth is not functional. The working Wi-Fi/display default remains the
earlier kernel recorded in `prebuilt/SHA256SUMS`. Do not reinstate the incoming
90 Hz kernel or force CPU/framebuffer boot options for Bluetooth experiments.
The user confirmed that the display regression disappeared after rollback.
The intended first Bluetooth use is headphones/speakers (Classic audio).

## Findings on this handset

The normal root does not contain a Bluetooth launch job. `userland/mkjobs.py`
excludes `bluetooth` and `BTServer` from automatically selected jobs. The system
image does contain `/usr/sbin/bluetoothd`; simply enabling its job is insufficient.
A separate SHARE root with a one-shot daemon job was RAM-tested before rollback.
It exited successfully after reporting that it could not find a Bluetooth
device-tree service or a valid local address, followed by “No bluetooth on this
device.” The probe is not part of the default root or boot flow.

A second probe supplied the loader's existing synthetic address via
`BT_DEVICE_ADDRESS`. The daemon logged the value but still rejected an all-zero
address. Static analysis during the retry explains this result: this particular
extracted daemon parses the environment variable with `sscanf`, then clears the
six-byte global address immediately afterwards. This is an observation about
this binary, not an explanation of why those instructions were introduced.

- Extracted daemon SHA256:
  `a315f41598a7d6271cafbdc11204944f3e75e6d10cd6375b322aafc34aef6889`.
- ARM64 virtual addresses `0x100026168` and `0x10002616c` clear four and two
  bytes at the global address, respectively. The Mach-O segment mapping places
  these at file offsets `0x26168` and `0x2616c`. Expected bytes are
  `5f0300b95f0b0079`.
- The subsequent availability path checks `/dev/cu.bluetooth` and
  `/dev/uart.bluetooth`. Neither device is implemented by this port.
- No binary patch was applied during the retry. Fixing the address gate alone
  would not provide a hardware transport.

Evidence is local and ignored: `build-tools/bt-inspect/bluetoothd.asm`,
`recovery/assets/bluetooth-probe-first.log`, and
`recovery/assets/bluetooth-probe-address.log`. Logs may contain personal device
and network data; do not publish them.

## Hardware path

The Renoir includes use the SM7350/Shima descriptions. In that tree Bluetooth
is `bt_qca6490`, distinct from the PCIe Wi-Fi transport:

| Component | Description |
| --- | --- |
| UART | GENI `qupv3_se15_4uart`, physical `0x99c000`, length `0x4000` |
| Clock | `GCC_QUPV3_WRAP0_S7_CLK`, plus wrapper AHB clocks |
| UART pins | GPIO 68–71; pinmux and flow control must follow Shima's definitions |
| BT enable | GPIO 65 |
| BT software control | GPIO 91 |
| Shared WLAN enable | GPIO 64; preserve the working Wi-Fi session |

The old comments about Bluetooth pins 85/86 in `redwood_wifi.c` describe the
Redwood/SM7325 path and must not be used as Renoir wiring.

Primary hardware references:

- [Renoir includes](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/renoir-sm7350.dtsi)
- [Shima Bluetooth power node](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/shima.dtsi)
- [Shima UART](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/shima-qupv3.dtsi)
- [Shima pinmux](https://github.com/LineageOS/android_kernel_xiaomi_sm8350/blob/lineage-23.2/arch/arm64/boot/dts/vendor/qcom/shima-pinctrl.dtsi)

## Remaining implementation and validation

Implement the correct power/clock and UART/HCI transport first, obtain a real
controller response, identify its ROM and matching firmware/NVM, then integrate
that transport and controller identity with the iOS daemon. Prove Classic
discovery, pairing and A2DP audio independently. A daemon that stays running or
a Settings switch that becomes available is not evidence of a working radio.

The factory Bluetooth MAC is not a prerequisite for continuing source work and
must not be guessed from Wi-Fi or copied from another handset. Once transport
works, attempt to read the controller address; use a locally administered
address only if the eventual controller initialization requires an override.

The user has declined rebooting for an address. Preserve the running session;
no new kernel can be hardware-validated in that session without replacing it.
At this checkpoint no Bluetooth controller driver, firmware loader or functional
fix had been implemented. That retry performed static analysis only and made
no phone writes or restarts.

## Initial protocol implementation

`xnu/files/bsd/dev/renoir_bt_h4.h` now provides an inactive, backend-independent
H4 framing and controller-probe core. It is not called by the kernel startup
path and has no MMIO access. A future serialized UART worker supplies output,
input, deadlines and QCA in-band-sleep handling. The output callback must not
reenter input processing.

Two explicit probes are available:

- `rbt_start_qca`: WCN3991-and-newer Qualcomm ROM identity request (`0xfc00`,
  subcommand `0x19`), decoding product, patch, ROM and SoC identity. It does not
  select or download firmware. Older vendor-event reply formats are unsupported.
- `rbt_start`: standard reset, local-version and controller-address commands,
  for use after the controller is running suitable firmware. This sequence is
  not a substitute for QCA ROM initialization or firmware loading.

The parser handles fragmented event input, skips ACL/SCO/ISO payloads instead
of interpreting them as event starts, correlates command replies and rejects
malformed replies, command errors and zero/broadcast addresses. The caller must
stop a probe on a deadline; no waiting or automatic retry occurs in this core.
A failed probe requires explicit reinitialization. QCA IBS acknowledgements,
UART hardware setup, firmware/NVM loading, the iOS device interface and audio
routing remain unimplemented. This code cannot enable Bluetooth by itself.

Validation: `ASAN_OPTIONS=detect_leaks=0 CC=clang python3
tools/test_bluetooth_h4.py` passes with ASan/UBSan, including byte-wise delivery,
maximum-length ACL skipping, truncated packets, mismatched replies, command
credits/errors, transport failure, controller identity and QCA ROM responses.
An ARM64 iOS 16.5 freestanding wrapper compiles with warnings treated as errors.
The default prebuilt SHA256 remains `2ba66e7e…`; no phone session was changed.

Protocol/hardware references consulted:

- [Linux v6.12 GENI UART](https://github.com/torvalds/linux/blob/v6.12/drivers/tty/serial/qcom_geni_serial.c):
  protocol check, FIFO setup, baud clock selection and command sequencing.
- [Linux v6.12 QCA UART](https://github.com/torvalds/linux/blob/v6.12/drivers/bluetooth/hci_qca.c):
  controller-specific power, speed, ROM query and firmware setup ordering.
- [Linux QCA protocol](https://github.com/torvalds/linux/blob/master/drivers/bluetooth/btqca.c):
  vendor version reply layouts and firmware selection. Local reference copies
  of `btqca.c` and `btqca.h` were read from the already verified Linux 7.0.14
  archive used by this repository, after a network fetch was rate-limited.

## Read-only physical UART survey and FIFO transport

The user authorized a brief RAM restart for a read-only probe and restoration
of the stable session. The probe build uses the Wi-Fi-tested source revision
`1aa1aa8` (its original XNU patch/files) plus the new survey, rather than the
incoming GPU/display changes. It is kept separately under
`xnu-src/renoir-bluetooth-stable`. The default prebuilt is unchanged.

The opt-in `bluetooth_probe=1` survey in `renoir_bluetooth.h` is called from
Wi-Fi initialization before evaluating the Wi-Fi boot flag. It requires both
the physical Renoir board and peripheral base, makes no MMIO writes, does not
consume FIFO data and avoids the UART aperture if its clocks are off. The
worker terminates explicitly on every path. Without the flag it does nothing.

Hardware result at early boot:

- GCC vote `0x083c93c0`, UART SE7 branch `0x80004220` (clock off).
- RCG command `0x80000000`, config `0x00100000`, DFS `0x8020`.
- BT enable GPIO65 low; UART pins GPIO68–71 still in GPIO mode.
- M-AHB branch `0`, S-AHB branch `0x8000000a` (hardware gated).
- UART MMIO was skipped because the serial-engine clock was off.

This is an early-boot snapshot, not evidence of the shared rails' state after
Wi-Fi completes initialization. No controller packet was sent. The probe was
stopped and the original stable kernel/root RAM session restored afterward.
Evidence: ignored `recovery/assets/bluetooth-stable-survey.log`.

Survey kernel: 15,645,480 bytes, SHA256
`58a0e5ac2254e37e9c30844904d45f6e311fdd4ce9ffaa267428ade311745a3a`.
The full source build exited successfully. The runtime probe remains separate
from the normal root and boot helper.

`renoir_bt_geni.h` now implements a hardware-independent UART FIFO engine with
8N1/CTS configuration, validated clock divider, little-endian byte packing,
bounded transmit/abort waits and partial-word receive accounting. It refuses
a busy sequencer, missing UART firmware, unsuitable FIFO geometry and excessive
baud error. The caller must first establish the correct power, clocks and
pinmux. This engine is not yet connected to hardware or the iOS daemon. It does
not implement DMA, interrupt delivery, IBS, firmware download or audio.

The Bluetooth test runner now exercises H4, survey gates and the FIFO register
model under ASan/UBSan. A freestanding ARM64 iOS wrapper compiles both protocol
and FIFO engines with warnings treated as errors. Recovery boot/payload and
Wi-Fi-start tests pass. The next hardware milestone is UART clock/pinmux setup
and a real Qualcomm ROM-version response. Functional Bluetooth remains pending.

## Reversible UART clock probe

`bluetooth_probe=2` now waits 30 seconds for existing startup work, requires
the wrapper clock votes already present, and temporarily adds only GCC vote
bit 17 (wrapper0 SE7). It never changes a shared AHB vote, regulator, RCG,
GPIO configuration or reset line. Every exit after adding the vote clears
only the bit this probe added; an existing UART vote is retained. The probe
remains disabled without the explicit boot argument.

The phone ran the separate stable-source clock-probe kernel successfully.
Observed hardware state:

- Votes `0x083c93ff` became `0x083e93ff` during the probe, then returned to
  `0x083c93ff`. The UART clock branch changed from off to `0x4220`.
- UART firmware revision `0x204`, protocol 2, FIFO interface enabled.
- Main/secondary sequencers idle; both FIFO status values zero.
- Hardware parameters `0x20102864` / `0x20204800`: 32-bit FIFO width,
  16 TX words and 32 RX words. QUP wrapper revision `0x30000000`.
- UART main clock config `0x11`, secondary config zero; current RCG is
  crystal-sourced (`cfg=0x100000`, DFS `0x8020`, DFS enable bit clear).
- At this later snapshot WLAN enable GPIO64 was high, BT enable GPIO65 low,
  BT software-control GPIO91 high and UART pins still in GPIO mode.

The last immediate branch read after removing the temporary vote was still
`0x4220`; the vote readback proves removal, not immediate physical clock halt.
The source was subsequently extended with a bounded wait to observe clock
gating after removal. That follow-up builds and passes host tests; its added
cleanup observation awaits the next hardware run. It does not add another
clock write.

Phone-tested clock-probe kernel SHA256:
`c695972865d5148a763b51fa940268303b1b0e8a1765062077df61cbbfe1f796`.
Follow-up cleanup-observer kernel SHA256:
`b8825eea001228e01d12f1d98e2f1cc19c2d43843218bedb83302572c7b866cc`.
Both are local ignored artifacts. Evidence:
`recovery/assets/bluetooth-clock-probe.log`. No controller packet was sent.
The stable session was restored after the experiment; the default prebuilt
remains unchanged.

Host tests cover missing wrapper votes, clock success and timeout, UART mapping
failure, wrong protocol, preservation of a pre-existing UART vote and cleanup
on each exit. The full stable-source XNU build succeeds. Next is a bounded
controller identity request: establish an accurate UART baud clock, validate
existing shared supply votes, configure the UART/pins, enable only BT_EN,
query the ROM and restore all temporary state. Firmware must be chosen from
the actual controller response, not the device-tree name alone.
