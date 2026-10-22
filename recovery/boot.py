#!/usr/bin/env python3
"""Boot restored Renoir RAM images. No flashing, erasing or storage commands."""
from pathlib import Path
import os, shutil, subprocess, time, struct
R=Path(__file__).resolve().parents[1]
fb=os.environ.get('FASTBOOT') or next((str(p) for p in [Path('C:/platform-tools/fastboot.exe'),Path('/mnt/c/platform-tools/fastboot.exe')] if p.is_file()),None) or shutil.which('fastboot')
if not fb:raise SystemExit('Install platform-tools or set FASTBOOT')
def file(p):
 p=str(R/p)
 return subprocess.check_output(['wslpath','-w',p],text=True).strip() if fb.endswith('.exe') and os.name!='nt' else p
def cmd(*args,serial=None,timeout=30):
 return subprocess.run([fb]+(['-s',serial] if serial else [])+list(args),capture_output=True,text=True,timeout=timeout,check=True)
def devices():return [line.split()[0] for line in cmd('devices').stdout.splitlines() if line.strip()]
def check(serial,key,value):
 q=cmd('getvar',key,serial=serial)
 if (key+': '+value) not in q.stdout+q.stderr:raise SystemExit('Wrong device: expected '+key+' '+value)
for p in ['userland/system.packfs','recovery/assets/renoir-ios-share.bin','prebuilt/renoir/resident-usb.img']:
 if not (R/p).is_file():raise SystemExit('Run recovery/restore.py first: missing '+p)
dev=devices()
if len(dev)!=1:raise SystemExit('Connect exactly one phone in fastboot mode')
s=dev[0]
if s=='xnuloader':raise SystemExit('Restart the phone into stock fastboot first; resident RAM may be in use')
if s!='xnuloader':
 check(s,'product','renoir');cmd('boot',file('prebuilt/renoir/resident-usb.img'),serial=s)
 for _ in range(60):
  if 'xnuloader' in devices():break
  time.sleep(1)
 else:raise SystemExit('Resident loader did not appear; do not flash anything')
s='xnuloader';check(s,'board','renoir');cmd('oem','ramdisk',serial=s)
print('Uploading system RAM image (about90 seconds)...',flush=True)
cmd('stage',file('userland/system.packfs'),serial=s,timeout=240)
# Refresh the epoch in the XNUP container without recompiling the kernel.
data=(R/'recovery/assets/renoir-ios-share.bin').read_bytes();out=bytearray(data[:8]);offset=8
while offset+24<=len(data):
 name,size,reserved=struct.unpack_from('<16sII',data,offset);offset+=24
 body=data[offset:offset+size];offset+=(size+15)&~15
 if name.rstrip(b'\0')==b'cmdline':
  words=body.rstrip(b'\0').decode().split();words=[w for w in words if not w.startswith('epoch=')]
  body=(' '.join(words+['epoch='+str(int(time.time()))])).encode()+b'\0'
 out+=struct.pack('<16sII',name,len(body),reserved)+body+b'\0'*((-len(body))%16)
(R/'recovery/assets/run-current.bin').write_bytes(out)
cmd('stage',file('recovery/assets/run-current.bin'),serial=s,timeout=60)
cmd('oem','run',serial=s);print('iOS started from RAM. No partition was flashed or erased.')
