# Renoir CSID580 / IFE-lite580 RAW capture

Implemented in redwood_camera.c and portable renoir_camera_core.h. Real Renoir
hardware bring-up receives recognizable S5KGW3 RAW frames. With camera streaming
explicitly enabled, real main-camera frames now reach Camera.app through
mediaserverd and the software ISP. Normal camera-disabled boot remains available.
Photo saving and front-camera preview in Camera.app still need device validation.

## Device validation, 20 October 2026

- Fixed recursive Renoir rail dispatch and restart admission after a drained ring
  (14a760c). The generic ARM MMIO VA window was also too small for simultaneous
  GPU, Wi-Fi, audio and camera mappings; a033a49 expands this board's reservation
  to 64 MiB while retaining the Apple default. This reserves VA, not physical RAM.
- GW3 native mode 7 is a central 2432x1824 unbinned crop. Main-camera default is
  now native mode 1, full-field 2x2 binning to 4640x3472. The user reports normal
  framing after this change; color accuracy has not been independently calibrated.
- Native DW9800 initialization acknowledges over CCI. A tap reached the contrast
  AF sweep: sharpness rose from 0.065 to 1.554 and the fine search settled at
  position 568. In a subsequent stationary, lit-text test the user confirmed that
  focus holds. Search speed remains slow; this is contrast AF, not vendor PDAF.
- All device launches use temporary RAM images through fastboot boot; no partition
  is flashed or erased. These observations do not establish shutter/Photos,
  video recording, front-camera UI, or sleep/wake reliability.


## Primary source audit

OKX tree commit 280947f54f7be0a09c8ce78a22f49e521e9033c9 and the previously captured
live Renoir Android DTB/DTS were used. Relevant files:

- cam_ife_csid_lite17x.c selects cam_ife_csid_lite_480_reg_offset for lite580.
- cam_ife_csid_lite480.h provides CSID RX/RDI/TPG registers and 3-bit PHY selector.
- cam_vfe.c selects cam_vfe_lite48x_hw_info for vfe-lite580.
- cam_vfe_lite48x.h, cam_vfe_top_ver3.c and cam_vfe_bus_ver3.c provide reset,
  bus-v3 register layout, frame mode, write master and IRQ configuration.
- cam_csiphy_soc.c selects 1.2.3 register tables for PHY1.2.4 and dynamic RX vote;
  cam_csiphy_1_2_3_hwreg.h and cam_csiphy_core.c provide D-PHY/reset/IRQ sequences.
- camcc-shima.c, gcc-shima.c, shima-gdsc.dtsi and the live DT provide clocks,
  domain control, mappings and the IFE stream mask.

## Implemented hardware path

- CSID-lite0 base 0x0acd9200, IFE-lite0 base 0x0acd9000, PHY0 0x0ac6a000 with
  stride 0x2000, six PHY slots (front uses PHY5, not a four-element array).
- CSID uses its shared 480/580 reset/RDI/TPG map; PHY selector is three bits and
  VC values above 3 enable the receiver's full-width VC mode.
- IFE bus-v3 uses reset at 0x0c, reset-done bit17, WM0 at 0x1c00, frame mode
  0x10001, packed CSI RAW10, frame completion at bus IRQ0 bit4, RDI update bit0.
  Bus-v2 registers are not used for Renoir configuration. DMA address/range and
  frame increment are bounded before any programming; setup failures stop WM0.
- PHY1.2.4 uses vendor D-PHY defaults, distinct clock-lane registers, lane/settle
  validation and IRQ clear/latch sequence. C-PHY is refused for these modules.
  Requested bit rate is checked against the selected 400MHz RX clock according
  to get_clk_voting_dynamic (rate/8+1). The vendor non-combo table configures all
  five lane positions, including unused ones, as Android does.
- Shima clock roots/branches include IFE-lite AHB/AXI, PHY-specific timer branches
  and 300MHz camnoc AXI. PLL0 uses Lucid5LPE parameters, preserves its configuration,
  refuses an already running/voted PLL, and restores its registers on failure/exit.
- SMMU stream 0x1000 with mask 0x440 comes from the live IFE DT node, replacing
  Redwood's 0x800/0x4e0. Existing serialized mapping/context rollback is retained.
- CX/MX ARC transactions use the shared RPMh lock, save TCS1 programming and
  APPS votes, never replay the prior trigger, decode returned status bits and
  preserve a later changed vote. RSC IRQ registers are global at 0xd00/04/08:
  the adapter maps TCS1's bit1 explicitly rather than polling offset0xfa4.
- Cache maintenance and DSB compiler memory clobbers are present in the capture path.

## Available modes and payloads

Default normal iOS has cameras off and no automatic audio tests. All prepared
normal payloads retain loader_return_after=0 and RAM packfs boot. Diagnostic
phone runs below use an isolated RAM root with a temporary return timer. No
partition writes were performed.

| Local logs/ payload | Mode |
| --- | --- |
| renoir-camera580-normal-phone.bin | normal iOS, camera disabled |
| renoir-camera580-tpg-phone.bin | cam=3, CSID TPG 1600x1200 |
| renoir-camera580-macro-raw-phone.bin | cam=4 macro, mode0, 2592x1944 |
| renoir-camera580-wide-raw-phone.bin | cam=4 wide, mode7, 2432x1824 |
| renoir-camera580-front-raw-phone.bin | cam=4 front, mode1, 2592x1940 |
| renoir-camera580-ultra-raw-phone.bin | cam=4 ultra, mode0, 3280x2464 |

Raw runs request eight frames and then power the camera down; iOS itself has no
return timer. Do not stop a user session just to collect ordinary logs. Frame
retrieval may require a deliberate kernel return; plan that with the user.

cam=5 and loader camera advertisement remain disabled on Renoir. This is because
continuous streaming, Bayer order, exposure/gain law (especially IMX355), autofocus,
orientation and actual iOS preview/capture still need implementation/validation.
Do not remove that guard merely because host tests or QEMU pass.

## Verification

- Source kernel build: logs/renoir-camera580-build.log.
- test_renoir_camera580.py executes the actual bus/PHY/TCS sequence with ASan/UBSan:
  register/DMA bounds, each setup write failing, reset/completion timeout, TCS
  restoration, malformed lane map and unsupported RX rate.
- test_renoir_camera580_csid.py executes actual shared CSID setup, verifies PHY5,
  full-width TPG VC and the actual global RSC IRQ adapter.
- test_renoir_camera580_clocks.py executes actual PLL0 configuration/rollback,
  every setup-write failure, lock timeout and active/voted PLL rejection.
- test_renoir_camera580_rails.py executes actual ARC ownership logic: higher prior
  vote, partial writes/timeouts, failed restore retry, later client and mutex.
- Existing camera power/board/parser/ISP tests and audio route/ring regressions pass.
- QEMU boot regression: logs/qemu-renoir-camera580-final.log: 90-second boot, SpringBoard running, normal return.
  QEMU does not emulate this camera hardware; it cannot validate these MMIO sequences.

## Required phone sequence

1. Verify installed vendor modules and sensor IDs with the power-only cam=2 payloads.
2. Run TPG first; inspect reset, ARC/clock acknowledgement, SMMU faults and complete
   frame count. Retrieve and verify the colour-bar frame and row stride.
3. Run one RAW sensor at a time; verify chip ID, packets/bytes, frame completion,
   absence of overflow/CCIF/SMMU faults and power rollback.
4. Determine correct Bayer orders from real RAW/test patterns, then implement the
   sensor gain/exposure/AF backend and enable continuous iOS streaming after testing.

Use fastboot boot only. Do not flash, erase, repartition or adopt APFS for this work.

## Hardware bring-up, 2026-10-19

- Installed Android vendor module SHA256 values match all four manifest entries.
- cam=2 identifies main S5KGW3 (0x7309), macro S5K5E9YX04 (0x559b), and ultra
  IMX355 (0x0355). Front S5K3T2 now identifies as 0x3142 after the EGPIO fix below.
- Corrected bus-v3 WM image_cfg_1 (horizontal initial offset: zero) and
  image_cfg_2 (DMA row stride). The old configuration produced SMMU overruns.
  RAW10 stride stays aligned to 16 bytes; frame increment is retained.
- After correction, main and macro bounded RAW captures finish without observed
  SMMU/CCIF/overflow faults and restore clocks, ARC votes and sensor power.
- Main mode1 (4640x3472), 60-frame runs produce recognizable scenes. The user
  confirmed the first scene was the power adapter; the subsequent laptop scene
  visibly changes to a laptop keyboard/display. Evidence: ignored local files
  logs/phone-camera-laptop.log, .raw and -proof.png.
- Laptop test: cam_shutter=3000, cam_gain=256; register readback verifies 0x0202
  = 0x0bb8, 0x0204 = 0x0100. 60 frames complete in about 3 seconds. The proof
  PNG subtracts black level64, averages all four Bayer phases and stretches the
  histogram for inspection; it is grayscale and does not validate Bayer order,
  white balance or orientation. It is not an iOS Camera.app photograph.
- Low-gain frames contain scene detail very close to black64. The old camraw.py
  first-look scaling does not subtract black, obscuring it. Never infer sensor
  failure from that rendering alone or from sampling only the top row.
- Minimal diagnostic root logs/camera-idle.packfs uses cpus=1, no GPU/Wi-Fi/audio
  initialization and loader_return_after=25. Normal +24 iOS image remains
  logs/renoir-clock24-normal-phone.bin. The resident system RAM image was cleared
  for these tests: restage system.packfs before resuming normal iOS.
- cam=5 and loader advertisement remain gated: continuous ring handling, sensor
  gain laws/descriptors, Bayer/orientation, autofocus, and app preview/capture
  must still be implemented and tested. No claim of a completed camera port.

### Front S5K3T2 bring-up

Shima GPIO176/177 power switches advertise EGPIO_PRESENT (CFG bit11). Android
msm_pinmux_set_mux enables ownership bit12 when that flag is set. The old camera
helper discarded those upper CFG bits, so both supplies appeared configured but
the front sensor never acknowledged. pin_config now preserves upper CFG bits and
sets EGPIO_ENABLE for Renoir only; saved-state restoration remains exact. It is
also used for active reset/MCLK and software-I2C pin setup. Hardware confirms
both supply CFGs change from 0x801 to 0x1a00 and sensor ID becomes 0x3142.

Front cam4 mode1 captures 60 RAW10 frames at 2592x1940 through PHY5, with expected
6285600 packet bytes and no observed SMMU/overflow/CCIF faults. Table defaults
leave exposure at six lines. The bounded-capture exposure override now admits
Renoir S5K3T2's existing SMIA hold/write sequence: shutter1500, gain32 reads back
as 0x05dc / 0x0020. Result is a recognizable ceiling/wall-shaped grayscale image;
a second scene aimed at the laptop now visibly shows its screen and surrounding room (logs/phone-camera-front-laptop-proof.png). Local evidence:
logs/phone-camera-front-egpio.log, phone-camera-front-exposure.log/.raw and
phone-camera-front-exposure-proof.png. This does not enable Camera.app streaming.

Camera power ASan/UBSan tests cover Renoir EGPIO-present and absent paths,
non-Renoir behavior, exact rail restoration and partial write failures. The
580 core, CSID/PHY5, board admission and rail ownership tests also pass.

Front second-scene regression: phone-camera-front-laptop.log/.raw; 60 frames at
2592x1940, expected packet byte count, no observed SMMU/CCIF/overflow faults;
sensor power, GPIO supplies, clock and ARC restoration completed. The grayscale
proof still has uncorrected orientation and is not Camera.app preview.

## Continuous capture bring-up

`git fetch origin` verified the current main on 2026-10-19. Its camera userland
(camera_device.c, camera_isp.c and inject_media.c) already matches our integrated
40a5d29 version, including daf7552 stream start on reservation. No extra camera
commit was missing; unrelated APFS changes remain excluded as requested.

Experimental Renoir cam5 now requires `cam_stream_test=1`. Normal boots without
that explicit flag still reject it. Only tested main/front sensor indices 1/2
are admitted by ios_select; usual modes are 7 and 1. Initial tested gain bounds were
conservative: main32..256, front32 (unity only); the native descriptor limits below supersede them. Other sensors remain unsupported
in streaming mode pending gain/write validation.

Lite580 frame-mode capture stalled after a single frame with Redwood's SOF-based
buffer updates, even with native frame increment. Re-arm the next DMA address
at completion as in the successful bounded RAW path. Ring selection excludes
the completed frame and any slot being copied by a reader, under ios_lock.
The real static-RAM phone probe completed 45 reads each from main -> front ->
main with close/reopen in between, no SMMU/CCIF/overflow fault. Evidence:
logs/phone-camera-stream-done-live.log. Host selector tests use the actual driver
helper with all reader-state combinations, under ASan/UBSan.

The first full iOS test had an invalid *compressed* small RAM image. Early GPU
firmware lookup explicitly rejects PACKFS_F_CHUNKED; unlike mounted packfs it
cannot decompress. GPU did not start and the user reported slow/broken rendering.
Do not use logs/renoir-camera-ios.bin (old compressed diagnostic). The corrected
logs/renoir-camera-ios-fixed.bin uses plain logs/renoir-camera-ios.packfs, checked
by tools/check_renoir_gpu_ramdisk.py against the local vendor files. The checker
also correctly rejects the bad image. Normal userland/root.packfs and the known
clock24-normal-phone.bin were not replaced. Full iOS preview is still unproven.

USB packaging must include `mkpayload.py --usb loader.efi=...`; without --usb the
loader does not stay resident. Corrected temporary image: logs/renoir-camera-usb.img.
Always fastboot boot; no partition writes.

### Installed sensor gain audit

Read-only ADB pull from the fully booted Android (sys.boot_completed=1,
SurfaceFlinger running), 2026-10-19:

- com.qti.sensor.renoir_ofilm_s5kgw3_wide.so, SHA256
  e5e8e30a3e4b2a6f88b069b1f335f3ca7cf31c52de2dfdc8a220d900cb4d68fd.
- com.qti.sensor.renoir_sunny_s5k3t2_front.so, SHA256
  2e1ebae3db87981cbbb63db9345a8f7d570de74ee6ba5a2108a967e19d9445a6.

GetSensorLibraryAPIs installs CalculateExposure at ELF VA0x1018 in each library.
Disassembly (ignored logs/renoir-vendor-{wide,front}.asm) shows gain clamped to
1..64 (wide) / 1..16 (front), converted to integer with five fractional bits
(fcvtzu w8,d3/d4,#5), with register cap2048 /512. Both therefore use unity32
and linear analog gain. Descriptors now use those native limits, superseding the
initial conservative32..256 /32-only bring-up limits. The earlier 45-frame
switching probe exercised the old conservative limits; broader dynamic AE is
not yet hardware-validated. No OTP or calibration was written.

## 2026-10-20 integration

See [the upstream ledger](upstream-20261020.md). New capture-graph, ISP, shutter, still-image and tuning code is integrated, while real Renoir streaming remains opt-in. Native DW9800 autofocus initialization is now implemented, but has not been tested on the phone. Main and front descriptors use GBRG order from the vendor mode tables and separate Renoir tuning; neither new orientation nor autofocus is hardware-certified. Reader lifetime now drains outstanding copies before freeing capture memory.
