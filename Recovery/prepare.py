#!/usr/bin/env python3
"""Restore local basecore changes after cloning this source branch recursively."""
from pathlib import Path
import subprocess, shutil
r=Path(__file__).resolve().parents[1];base=r/'Mu_Basecore';patch=r/'Recovery/Mu_Basecore.local.patch'
subprocess.run(['git','submodule','update','--init','--recursive'],cwd=r,check=True)
expected=(r/'Recovery/Mu_Basecore.BASE').read_text().strip()
actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=base,text=True).strip()
if actual!=expected:raise SystemExit('Unexpected Mu_Basecore revision; refusing to apply backup patch')
if subprocess.run(['git','apply','--reverse','--check',str(patch)],cwd=base,capture_output=True).returncode==0:
 print('Basecore recovery patch already applied')
else:subprocess.run(['git','apply',str(patch)],cwd=base,check=True)
(r/'.xnu-device').write_text('renoir\n')
# The existing Linux build used system NASM instead of a Mono/NuGet download.
if shutil.which('nasm') and shutil.which('ndisasm'):
 d=base/'BaseTools/Bin/mu_nasm_extdep'
 if not (d/'extdep_state.yaml').exists():
  (d/'Linux-x86-64').mkdir(parents=True,exist_ok=True)
  (d/'extdep_state.yaml').write_text('version: 20016.1.1\n')
  for name in ['nasm','ndisasm']:(d/'Linux-x86-64'/name).symlink_to(shutil.which(name))
print('Renoir source tree restored; see Recovery/README.md')
