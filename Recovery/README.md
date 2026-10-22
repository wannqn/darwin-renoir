# Renoir iOS loader source snapshot

This branch preserves the actual Mu-Silicium source used for RAM boot, including
BootShim payload placement, XNU BootManager dispatch, memory reservation and
basecore local patches. It is independent of the kernel branch in this repository.

```sh
git clone --branch silicium-renoir --single-branch --recursive https://github.com/wannqn/darwin-renoir.git Mu-Silicium
cd Mu-Silicium
python3 Recovery/prepare.py
python3 -m venv venv
venv/bin/pip install -r pip-requirements.txt
PATH="$PWD/venv/bin:$PATH" python3 build_uefi.py -d renoir -r RELEASE
```

Keep the directory beside the kernel clone, or name it Mu-Silicium inside it as
mkxnuimg.py expects. Submodule revisions are pinned by Git. prepare.py restores
the local Mu_Basecore changes; never discard them as incidental dirt.
USE_CUSTOM_DISPLAY_DRIVER stays0: the90Hz experiment did not boot and is not the
working configuration. No partition should be flashed or erased. The kernel
branch documents the ready-built recovery image and RAM-only boot commands.
