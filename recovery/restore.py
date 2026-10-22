#!/usr/bin/env python3
"""Download this private backup's release assets, verify them and restore RAM boot inputs."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, os, subprocess, tarfile
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4<<20),b''):h.update(b)
 return h.hexdigest()
def unpack(path):
 with tarfile.open(path) as tf:
  members=tf.getmembers();links={x.name.rstrip('/') for x in members if x.issym()}
  for x in members:
   p=PurePosixPath(x.name)
   if p.is_absolute() or '..' in p.parts or x.isdev():raise SystemExit('Unsafe archive member')
   if any(str(parent) in links for parent in p.parents):raise SystemExit('Archive writes through a symlink')
   if x.islnk() and (PurePosixPath(x.linkname).is_absolute() or '..' in PurePosixPath(x.linkname).parts):raise SystemExit('Unsafe hardlink')
   if x.issym() and x.linkname.startswith(META['old_root']+'/'):x.linkname=str(ROOT)+x.linkname[len(META['old_root']):]
  tf.extractall(ROOT,members=members,filter='fully_trusted')
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--build-inputs',action='store_true');p.add_argument('--verify-only',action='store_true');a=p.parse_args()
META=json.loads((ROOT/'recovery/manifest.json').read_text());assets=ROOT/'recovery/assets';assets.mkdir(parents=True,exist_ok=True)
selected=[x for x in META['assets'] if a.build_inputs or x['name']!='build-inputs.tar.gz']
for x in selected:
 f=assets/x['name']
 if not f.exists():subprocess.run(['gh','release','download',META['tag'],'--repo',META['repository'],'--pattern',x['name'],'--dir',str(assets)],check=True)
 if f.stat().st_size!=x['size'] or sha(f)!=x['sha256']:raise SystemExit('Checksum mismatch: '+f.name)
 print('Verified',f.name,flush=True)
if a.verify_only:raise SystemExit(0)
for name in ['userland','fw-gpu','fw-wifi','fw-audio','fw-camera']:(ROOT/name).mkdir(exist_ok=True)
for dest,parts in [('userland/root.packfs',['root-share.packfs']),('userland/system.packfs',['system.packfs.part00','system.packfs.part01'])]:
 target=ROOT/dest;tmp=target.with_suffix('.restoring')
 with tmp.open('wb') as out:
  for part in parts:
   with (assets/part).open('rb') as src:
    for b in iter(lambda:src.read(4<<20),b''):out.write(b)
 os.replace(tmp,target)
 if sha(target)!=META['images'][dest]:raise SystemExit('Restored image checksum mismatch')
unpack(assets/'renoir-firmware.tar.xz')
if a.build_inputs:unpack(assets/'build-inputs.tar.gz')
print('RAM images and native firmware restored. Wi-Fi credentials are deliberately absent. See recovery/README.md.')
