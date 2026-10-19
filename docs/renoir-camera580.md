# Renoir CSID580 / IFE-lite580 RAW capture

Implemented in redwood_camera.c and portable renoir_camera_core.h. Hardware has NOT
been exercised yet: the user is away. This is an implementation ready for staged
bring-up, not a claim that real sensor frames or iOS Camera already work.

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
payloads retain loader_return_after=0 and RAM packfs boot. No phone operations
or partition writes were performed.

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
