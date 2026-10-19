# Renoir status bar clock offset

The initial correction is **+12 logical points to the right** (about 35 physical
panel pixels with this port's current display scaling). Change
`RENOIR_CLOCK_SHIFT_POINTS` in `userland/src/statusbar.c` to tune it.
This moves the small status bar clock, not the large Lock Screen clock.

## Layout and lifecycle

The iPhone X / iOS 16.5 (20F66) UIKit cache uses
`+[_UIStatusBarVisualProvider_Split1125 leadingCenteringOffset]` in
`-[_UIStatusBarVisualProvider_FixedSplit leadingCenteringEdgeInset]`.
The native `pillCenteringEdgeInset` derives from that same leading inset.
The hook returns Apple's original metric plus 12 on every call, so both ordinary
clock and activity pill use UIKit's own layout, animations and replacement views.
It never modifies a view frame, transform, text width, hidden flag or alpha.
Repeated layout does not add to an already shifted position.
The right-hand region and application safe-area insets are unchanged.

The hook checks `/chosen/darwin-board` for exactly `renoir`; the loader sets this
from the selected physical platform independently of the Apple userland identity.
Redwood and QEMU retain their original layout in a normal build. The method ABI
and original unslid IMP (0x189225384) must match this iOS cache. Other versions or
another existing hook are left alone instead of guessing addresses.

SpringBoard gets the code in its existing injection library. Apps get the small
`libredwood-statusbar.dylib`, since their UIKit status bars live in their own
processes. The new `@apps` injection selector matches saved executable paths under
`/Applications/`, `/private/var/containers/Bundle/Application/` and
`/var/containers/Bundle/Application/`, including executables with spaces in their
names. Existing named injection groups still work. Do not use an older kernel
with the new root image if consistent app status bars are required.

## Build and rollback

Build the current kernel and small RAM image together:

```sh
./xnu-build.sh -j6
GL=1 REST=1 WIFID=1 PACK_JOBS=2 RC_JOBS=rc.jobs.renoir bash userland/build.sh
```

No change to system.packfs, UEFI or phone partitions is needed. Boot using the
existing RAM-only fastboot boot / xnuloader procedure. Revert the isolated status
bar commit and rebuild the kernel, root.packfs and payload to undo it; a git
revert alone does not replace a payload that was already built.

## Validation

`python3 tools/test_statusbar_exec.py` compiles the actual exported kernel parser
and checks application paths, names containing spaces, similar non-matching paths,
ordinary daemon exclusion and existing named groups. It also checks the real
board-gating function with exact names/lengths, missing DT and incorrect CF types
under ASan/UBSan. Kernel and userland builds
pass, and the exported patch reverses cleanly against the local XNU source tree.

`tools/statusbar_test.c` is a diagnostic tool linked with UIKit. On QEMU the
normal library passes 10,000 calls with the original metric -0.666667 unchanged.
A separate diagnostic library built with `-DRENOIR_STATUSBAR_TEST` passes 10,000
calls with metric 11.333333 (+12). That macro is **not** used in normal builds.
Never put diagnostic jobs or the test macro in the normal image.

The long QEMU run was allowed at least five minutes to start the UI (short
runs showed only the boot logo/black transition and were not visual failures).
Home screen and Settings both show the shifted clock. Preferences logs confirm
that the application constructor installed the same +12-point metric. Turning
the screen off, on and unlocking back to Settings preserves the clock position.
Evidence: `logs/qemu-renoir-clock-long.log`, `logs/clock-long-5min.png`,
`logs/clock-current.png`, `logs/clock-after-power-cycle.png`.
A completely fresh QEMU boot repeats the 10,000-call +12 test successfully and
shows the shifted clock again after allowing five minutes for UI startup. See
`logs/qemu-renoir-clock-reboot.log` and `logs/clock-after-full-reboot-settled.png`.

Physical phone checks still need hole-punch clearance, Safari, orientation
changes, 12/24-hour time and an activity pill. Normal iOS hiding of the status bar in a
fullscreen application remains native behavior.
