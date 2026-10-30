# Personal Renoir backup repository

The user explicitly authorized this private GitHub backup, overriding upstream's
GitLab-only publication rule for this fork. Upstream remains GitLab hackios/hackios;
never push to upstream unless separately requested.

- Kernel/environment branch: renoir. UEFI source branch: silicium-renoir.
- Target for this backup: https://github.com/wannqn/darwin-renoir.git only.
- No force push. Keep commits focused; use descriptive English conventional titles.
- Never publish passwords, access tokens or private keys. Runtime recovery images
  must be built with SHARE=1. Keep firmware separate from personal network config.
- Phone testing is RAM-only: fastboot boot, resident stage/oem run. Never flash,
  erase, unlock or repartition. Persistent-storage APFS boot remains excluded; APFS images may boot from RAM only.
- Before deleting local work verify branch heads, release assets and SHA256 checks.
