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
