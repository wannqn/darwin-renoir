Renoir RAM-only recovery snapshot. Source branches: renoir and silicium-renoir.

Six recovery assets plus SHA256SUMS, approximately 3.6 GB. SHARE=1 images omit
the Wi-Fi password and SSH keys. Native firmware and radio MAC are preserved.
Build inputs contain Theos SDK/toolchain, XNU host dependencies and QEMU.
Ready packfs images are included. Original Apple IPSW inputs can be downloaded
again for rebuilding userland; they are not needed for booting the saved images.

Start with recovery/README.md. This is RAM boot only. Latest changes were built
and QEMU-tested; the new combination has not been revalidated on the phone.
