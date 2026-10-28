# Renoir vendor inputs

The `renoir` branch includes the board-specific binary inputs used by this port:

- `fw-gpu/renoir`: Adreno GPU firmware and signed ZAP segments.
- `fw-wifi/renoir`: QCA6490 firmware, Renoir board data and regulatory database.
- `fw-audio/renoir`: ADSP firmware segments and the TFA speaker container.
- `fw-camera/renoir`: sensor modules, colour tuning and actuator metadata.

These are vendor binaries/data, not editable driver source. GPU, Wi-Fi and audio
inputs were copied from this Renoir's Android installation. Camera input provenance
and checksums are recorded in `tools/renoir-camera-{modules,tuning}.json`.
They retain their respective vendor ownership; inclusion does not relicense them
under XNU's APSL. This private repository is the user's device recovery backup.

`recovery/firmware-manifest.json` records exact sizes and SHA256 hashes. Userland
build scripts consume these directories directly and regenerate camera tables.
No additional firmware download or Android extraction is needed after cloning.
Network passwords, the per-device `fw-wifi/mac` file and private keys are excluded.
Run `python3 recovery/boot.py` and enter your device MAC when prompted, or supply
`--wifi-mac YOUR_DEVICE_MAC`. This sets `wifi_mac` for the handset being tested.
It is not firmware.
