# Renoir GPU and display investigation

The normal Renoir GPU profile runs the Adreno 642 at 285 MHz. The Android device tree for shima lists 365 MHz at RPMh LOW_SVS_L1 (level 80), including speed bin 105, which the test phone reported. The 365 MHz entry is available only when `adreno_speed=2` is passed; the default remains 285 MHz. A RAM-only phone test measured 365.001 MHz and reached the home screen, with no reported GL errors in the captured log. The workloads differed, so those frame averages do not establish an improvement or stability over time.

A transition screenshot still showed horizontal frame splits. The current framebuffer driver copies into the boot framebuffer and reports vsync from a timer; frequency alone does not synchronize scanout. A direct read-only probe of MDP registers was followed by loss of USB and Android reboot. The probe was removed immediately; the cause is not confirmed. Do not repeat the unguarded access. The downstream Renoir display clock driver places MDSS AHB at offset 0x2080 in dispcc, unlike the existing Redwood diagnostic. Clock/power sequencing, display SMMU mapping and atomic update/commit must be identified before attempting scanout changes.

For an objective comparison, run identical automated touch sequences with `touch_lat=1`, save complete logs, and analyze with `tools/frames.py` at each frequency. Separate display tearing tests need timed panel observation or a verified capture method.

Sources: [Renoir GPU device tree](https://github.com/Official-Ayrton990/android_kernel_xiaomi_renoir/blob/downstream/arch/arm64/boot/dts/vendor/qcom/shima-gpu.dtsi), [Renoir display clock driver](https://github.com/Official-Ayrton990/android_kernel_xiaomi_renoir/blob/downstream/drivers/clk/qcom/dispcc-shima.c), [Renoir display device tree](https://github.com/Official-Ayrton990/android_kernel_xiaomi_renoir/blob/downstream/arch/arm64/boot/dts/vendor/qcom/display/shima-sde-common.dtsi), [ios-macan](https://github.com/hxfuxyy/ios-macan).

## RAM-only latency comparison (2026-10-29)

The archived normal payload used `cpus=4`. A `touch_lat=1` diagnostic kernel
marked the start of the final framebuffer copy without changing rendering.
During an automated Settings/scroll/home sequence, 980 presented frames had
median display composition 4.34 ms and final framebuffer copy 3.93 ms; these
intervals happen **after** the window server's render and are not a GPU clock
measurement. The first run also contained physical touches, so it was not used
for the CPU comparison.

For the comparison, `touchscreen=0` disabled only the physical FT3658U input;
the same `/redwood/bin/rwtouch` job supplied eight identical gestures in each
RAM run. `tools/frames.py` reported:

| Gesture | `cpus=4` | `cpus=8` |
| --- | ---: | ---: |
| Settings icon tap (two runs combined) | 38.1 frames/s | 41.6 frames/s |
| Settings list scroll down | 58.9 frames/s | 60.0 frames/s |
| Settings list scroll up | 58.3 frames/s | 58.9 frames/s |
| Home-edge swipe | 44.2 frames/s | 43.0 frames/s |
| All gestures, gaps over 33 ms | 5% | 5% |

The current `recovery/boot.py` now replaces the normal payload's `cpus=4` with
`cpus=8` in RAM; `--last-phone-good` keeps its archived boot arguments. A normal
boot through that helper reached the home screen with `cpus=8` in the phone log,
and reported three + three + one cores in its frequency groups. This is a
modest improvement to app opening, **not** a fix for all lag or frame tearing:
closing did not improve, and the physical touchscreen was disabled in the
controlled comparison. Its normal-boot screenshot and the scripted Settings
screenshot were visually intact. Eight active cores may draw more power.

The downstream display tree lists a DSI TE interrupt, but the RAM driver still
uses the boot framebuffer and timer-based pacing. No safe live TE IRQ route or
physical panel phase was verified on this boot. Do not write display registers
or substitute a TE wait on the basis of the Android tree alone; that could
hang this device. The panel's UEFI profile requests 60 Hz; increasing only the
software-reported rate does not change the panel's refresh.

## APFS RAM boot and Mesa 26.2.5 (2026-10-30)

The previous working tree was committed and pushed as `a683cb05` before this
cutover. The current source builds Mesa 26.2.5 from the verified consolidated
`ios-dodge` donor patch plus a Renoir A642/Gen6 device profile; Gen8/OnePlus
hardware configuration is not used for Renoir.

Both APFS images passed `apfsck -cw` and independent content verification:
61,249 entries for the 2,495,967,232-byte system image and 484 entries for the
14,397,440-byte supplemental image. The preserved packfs recovery artifacts
remain inputs for conversion and the explicitly paired `--last-phone-good`
legacy boot; the default boot uses APFS images.

The physical phone boot confirmed:

- `/`: read-only APFS, flags `0x4005001`.
- `/redwood`: read-only APFS on `/dev/md1`, flags `0x4001001`.
- `/private/var`: writable ramfs, flags `0x4001000`; explicit
  write/read/unlink succeeded.
- PID1 smoke checks: `40 checks, 0 failed`.
- CoreAnimation: `OpenGL ES 3.2 Mesa 26.2.5; FD642`, GLSL ES 3.20, shader
  preparation and BGRA IOSurface import followed by GPU-rendered frames.
- A fresh loader screenshot showed the home screen with text, icons and
  wallpaper. Some widget content was still unloaded.

Separately, QEMU exercised Mesa's explicit software path: `softpipe`, OpenGL
ES 3.1 Mesa 26.2.5. A 64x64 triangle readback reported GL error 0, correct
red/green/blue corner samples and 1,054 covered pixels out of 4,096. QEMU
does not validate the physical GPU.

The first phone attempt returned during GPU step 20 before userspace. After
booting Android far enough for SurfaceFlinger to initialize, then returning
to stock fastboot, the APFS/Mesa boot succeeded. Re-entering the resident
loader alone is not evidence of a fresh GPU state.

No controlled before/after animation-latency comparison, sustained GPU stress
test or physical tear-free scanout verification was completed for this
cutover. A shadow-buffer copy, including a parallel copy, is not an atomic
page flip and does not establish TE/vblank synchronization.

## UI latency measurement and fixes (2026-10-30)

All runs were RAM-only: Android booted until SurfaceFlinger was up, `adb reboot bootloader`,
`fastboot boot` of the resident loader, then the APFS system and payload staged and run. Nothing was
flashed. Each run used the same scripted gestures (`RC_JOBS=rc.jobs.latency-bench`: home-screen page
swipes, Settings opened/scrolled/closed, Notes and Clock opened/closed, three rounds) with
`touch_lat=1 touchscreen=0`, so physical touches could not disturb it:

```sh
SHARE=1 GL=1 RC_JOBS=rc.jobs.latency-bench userland/build.sh
python3 recovery/boot.py --boot-arg touch_lat=1 --boot-arg touchscreen=0
# about four minutes later, from the resident loader
fastboot -s xnuloader oem log && fastboot -s xnuloader get_staged RUN.log
python3 tools/smoothness.py RUN.log
```

`tools/smoothness.py` counts refreshes missed during the 0.7 s after each touch (the gesture and its
main animation) and charges each to the stage that held the frame. `tools/frames.py` counts every
frame step over 16.7 ms, which uneven but complete pacing inflates; later frames after an animation
are not missed refreshes. Runs of the same build varied by about two percentage points.

| Build | Frames/s in gestures | Refreshes missed | SpringBoard busy | Render CPU | GPU | Present |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Before (checkpoint kernel) | 46.8 | 23.0% (178) | 62 | 61 | 28 | 22 |
| Current defaults | 50.1 | 16.8% (128) | 64 | 26 | 29 | 6 |

Changes that produced this:

- `to_memory()` is `dc civac` again and the IOSurface flush rule is the donor's (`!b->seen`,
  `GPU_PUSH_AGAIN_MS` 4). The earlier `dc cvac` change let `gmu_data()` and CPU reads of
  GPU-written memory see stale lines; the `seen` removal could hand the GPU unflushed CPU writes.
- The presenter gives back a swap's queue slot only after the frame is in the panel's memory, and
  drops a swap whose surface the GPU has not finished instead of showing it.
- `fb_double` defaults to 0. The shadow copy hid no tear without TE or a page flip, and measured
  5.4 ms instead of 3.1 ms per presented frame (median), with about twice as many window-server
  frames over 16 ms.

Measured and ruled out: kernel vsync delivery (no tick over 1 ms late, no notification toggles);
CPU clocks (1.8–2.2 GHz measured by `cpu_test`); GPU submit cache flushes (0.1–0.2 ms per
submission); `gpu_cached=1` (worse); big cores only (`cpus=4`, same); nearest-neighbour scaling
(within noise).

Remaining misses are mostly outside this driver:

- Half come from SpringBoard's main thread running 100–350 ms turns at the start of the home
  gesture and on app launch. `sb_sample=1` (with `touch_lat=1`) samples that thread every
  millisecond and logs where long turns spend time (`tl: A`, `tl: B`): about 90% is CPU time in
  SpringBoard/UIKit/BaseBoard transition code with no single hotspot. On the first launch of an
  app, about 100 ms more is a synchronous wait for SplashBoard launch-image generation; `/var` is
  RAM, so this repeats after every boot.
- The rest is the window server's own CPU drawing through Mesa and GPU time on heavy transition
  frames.

## Presentation synchronized to the panel (2026-10-30)

`display_probe=1` now also runs on Renoir with Renoir's own addresses (shima device tree: dispcc
GDSC `0xaf03000`, MDSS AHB `0xaf02080`, DSI interface intf1 `0xae6b800`; Redwood's intf is at
`0xae36000`). The earlier crash is consistent with reading the display block without its register
clock or at Redwood's addresses. The probe makes the same two clock-enable writes as on Redwood
and nothing else. Result on the phone: intf1's timing engine is off and its frame counter advances
60.0 times a second. **The panel is in command mode**: at each panel refresh the controller reads
the framebuffer out in about 8.6 ms (line counter 1 to 2400, about 278 lines/ms) and stands at
line 1 in between.

The framebuffer driver uses these counters by default (`fb_scan=1`; `fb_scan=0` restores the
unsynchronized behaviour, and boards without the counters fall back automatically):

- The window server's vsync notifications are the panel's readout starts, phase-locked to the
  counter, not a free-running 60 Hz timer that drifts against the panel.
- Each frame is written for one readout (`target`), strictly after the previous frame's. All
  drawing threads go down the frame together in interleaved 16-row stripes. A stripe waits until
  the previous readout has read it and must be done before its readout reaches it, so the readout
  shows the whole new frame. The lead before the target adapts: +0.5 ms after a frame with a late
  stripe, -0.1 ms after 60 clean frames.

Phone run (same scripted gestures, `touch_lat=1 touchscreen=0`): 1933 of 1933 frames were
synchronized and only 8 (0.4%) had a stripe written late, the only frames that can tear. The lead
settled at a median of 3.5 ms. From the presenter starting a frame to the panel reading it took a
median of 14 ms: one refresh from vsync to display. Refreshes missed during gestures were 19.6%,
within the 16.8–19.7% range of the unsynchronized runs. A frame that misses its readout now waits
for the next one instead of appearing torn mid-readout. `tools/smoothness.py` uses the readout
(`target`) as the display time when it is logged.

Not done: hardware page flipping and 90/120 Hz (the panel is driven at 60 Hz). The remaining
missed refreshes are SpringBoard's main thread, the window server's CPU drawing and GPU time, as
described above.
