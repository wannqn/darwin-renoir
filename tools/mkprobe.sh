#!/bin/bash
# Build a small, persistent PID1 ramdisk for RAM-only hardware diagnostics.
set -euo pipefail
cd "$(dirname "$0")/.."
source ./xnu-env.sh
mkdir -p logs/wifi-probe-root/sbin logs/wifi-probe-root/dev
if [ "${WIFI_FW:-0}" = 1 ]; then
  mkdir -p logs/wifi-probe-root/fw-wifi-renoir
  for f in amss20.bin m3.bin bd_k9gl.elf regdb.bin; do
    cp "fw-wifi/renoir/$f" "logs/wifi-probe-root/fw-wifi-renoir/$f"
  done
fi
if [ "${WIFI_NETWORK:-0}" = 1 ]; then
  mkdir -p logs/wifi-probe-root/fw
  install -m 0600 fw-wifi/network logs/wifi-probe-root/fw/network
fi
xnu-clang -arch arm64 -Os -static -nostdlib -ffreestanding \
  -fno-stack-protector -fno-builtin -Wl,-e,_start \
  -Wl,-pagezero_size,0x100000000 tools/probe_pid1.c \
  -o logs/wifi-probe-root/sbin/launchd
python3 mkpackfs.py -o logs/wifi-probe.packfs logs/wifi-probe-root
