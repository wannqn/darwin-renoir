# Renoir camera port: implementation checkpoint, 2026-10-19

Status: NOT working yet. The five upstream camera source changes are integrated and build,
Renoir now has cam=1 inspection, cam=2 sensor-power/ID, cam=3 TPG and cam=4 RAW
capture implementations. Hardware capture is still untested. cam=5 iOS streaming
remains disabled. See renoir-camera580.md for the implemented backend and tests.
User requires working camera support, not just common-code integration. APFS and flash changes
are explicitly excluded; retain packfs RAM boot and fastboot boot only.

## Upstream review

Fetched origin/main through 1dc0537; 80 commits since the previously reviewed 08dd6f1.
Camera source changes selected: 8142325, c453fed, 62fac13, e3cdc7c, daf7552.
Their aggregate five-file source diff equals the same files at origin/main.
Prebuilt binaries are not imported. APFS/UFS, partitioning tools, replacement of packfs,
and APFS firmware lookup changes in Wi-Fi/GPU/ADSP are not imported.
Existing Renoir audio/haptics work is retained separately and remains uncommitted.

## Board differences verified from local primary sources

Sources: OKX arch/arm64/boot/dts/vendor/qcom/camera/renoir-sm7350-camera-sensor.dtsi;
drivers/clk/qcom/camcc-shima.c; previously captured live Android device tree
(logs/android-renoir-live.dts). Public Renoir vendor modules are available from TheMuppets/proprietary_vendor_xiaomi_renoir
(branch lineage-23.2). Their exact Git blob IDs, SHA-256 and sizes are recorded in
tools/renoir-camera-modules.json. All four were downloaded and checksum-verified.
The actual phone still needs to confirm these IDs before capture is enabled.

| Slot | CCI/master | SDA/SCL GPIO | Reset GPIO | MCLK GPIO | CSIPHY | Supplies |
| --- | --- | --- | --- | --- | --- | --- |
| wide 0 | 0/1 | 109/110 | 117 | 101, MCLK1 | 1 | L5I 1.8V, L1I 1.056V, L6I 2.8V, actuator L3I 2.8V |
| front 1 | 0/0 | 107/108 | 126 | 100, MCLK0 | 5 | L5I 1.8V, GPIO177 1.05V, GPIO176 2.8V |
| macro 2 | 1/0 | 111/112 | 116 | 104, MCLK4 | 0 | L5I 1.8V, L4I 2.8V, L2I 1.2V, actuator L3I 2.8V |
| ultra-wide 3 | 1/1 | 113/114 | 119 | 102, MCLK2 | 3 | L5I 1.8V, L7I 2.704V, L2I 1.2V |

PM8008i reset is PM8350C GPIO7 in the live DT; Redwood uses GPIO3.
MCLK root offsets 0xe000/0xe01c/0xe038/0xe054/0xe070/0xe08c are present in
camcc-shima.c; all branch, domain, PLL, interconnect, CSIPHY/CSID/IFE and SMMU
settings still require explicit comparison before enabling hardware operations.
The camera PMIC bus pins, address mapping and rollback rules must be verified as well.
Do not enable the Redwood table by merely removing its board guard.

Reproduce the verified module/table preparation with `python3 tools/fetch_renoir_camera.py`.
This downloads only to the host. The build consumes these tables through packfs.

## Implemented offline

- Explicit Renoir profiles: macro S5K5E9YX04 (ID 0x559b, slave 0x5a), wide
  S5KGW3 (0x7309, 0x20), front S5K3T2 (0x3142, 0x20), ultra IMX355 (0x0355, 0x34).
  Slave addresses here are the vendor modules' 8-bit addresses.
- Actual PM8008i bus GPIO0/1 on QUP5, PM8350C GPIO7 reset with VIN1,
  shima titan-top GDSC offset 0xc120 and GCC camera XO offset 0x26020.
- VAF power step 4 supported, including wide sensor L3I. Front GPIO176/177
  have independent journals, including partial-write rollback and preservation
  of a supply that was on before the driver started.
- PMIC write-time channel ownership rechecked.
- Table parser uses sensorDriverData's symbol offset, not the data pool's start:
  the front module wraps it in cameraModuleData, unlike the original assumptions.
- Build packs board-prefixed camera-renoir-*.tab in the existing packfs /fw.
  No Redwood table fallback; no APFS, UFS or flash changes.
- Renoir cam=1/2 power bring-up and cam=3/4 TPG/RAW capture are available; cam=5 refused before MMIO.
  Default boot does not enable cameras, and loader camera advertisement remains off.

## Capture backend checkpoint (superseded by renoir-camera580.md)

The live DT identifies CSID/IFE-lite580 and CSIPHY1.2.4. OKX maps the first two
onto cam_ife_csid_lite_480_reg_offset and cam_vfe_lite48x_hw_info; CSIPHY1.2.4
uses 1.2.3 register tables with dynamic clock voting. This is not the Redwood
IFE-lite16x register layout. Actual bases are CSID-lite0 0x0acd9200,
IFE-lite0 0x0acd9000, CSIPHY0 0x0ac6a000 (stride 0x2000).
Clocks, SMMU stream matching, IRQ bits and bus-v3 write masters now have a separate
Renoir cam=3/4 implementation. Physical validation and sensor exposure/gain/AF
semantics are still required before iOS streaming.
In particular IMX355's gain law must not be assumed to be Samsung's linear gain.

## Next hardware test and subsequent implementation

1. Read-only Android collection when user returns; compare installed modules and
   camera service IDs against downloaded vendor modules and saved live DT.
2. RAM boot each logs/renoir-camera-board-{macro,wide,front,ultra}-phone.bin.
   These run cam=2 only: power sequence, ID read, power down. They do not start
   image capture, initialize sensor registers or claim working iOS cameras.
3. Verify ID, PMIC status and restored power state; then implement/test TPG,
   sensor RAW capture, ISP, autofocus and iOS preview/capture/switching.
4. Use only fastboot boot/stage/oem run. No partition writes, no flash/erase.

## Checks

Kernel and source-built userland compiled successfully; packfs retained, all four
sensor tables present in root/fw. Host tests pass:
- test_camsensor_driver.py: flat/wrapped driver and absent/truncated symbol.
- test_renoir_camera_power.py: real supply functions, dual GPIOs, partial failure,
  previously-on rail preservation, VAF and unsupported power step.
- test_renoir_camera_board.py: actual init; Renoir cam=3/4 admitted and cam=5 rejected before thread/
  allocation, distinct table names and unknown-board guard.
- test_camera_isp.py: actual ISP, RAW10 black/grey/white, all Bayer orders, output
  ranges, row-band equivalence and output stride padding under ASan/UBSan.
- Existing Renoir PCIe config, audio route and concurrent PCM ring regressions.

QEMU source-integration boot passed 90 seconds with SpringBoard running and normal
return, logs/qemu-renoir-upstream-camera-20261019.log. Final board-build regression:
logs/qemu-renoir-camera-board-20261019.log: 90 seconds, SpringBoard running and normal return.
Prepared no-timer, no-boot-tone payloads on the host only. Normal payload:
logs/renoir-camera-board-normal-phone.bin. No phone interaction this session.
