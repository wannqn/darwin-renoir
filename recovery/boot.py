#!/usr/bin/env python3
"""Boot restored Renoir RAM images. No flashing, erasing or storage commands."""
from pathlib import Path
import os, shutil, subprocess, time, argparse, re
from payload import prepare, validate_mac
R=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
def mac_argument(value):
 try:return validate_mac(value)
 except ValueError as error:raise argparse.ArgumentTypeError(str(error)) from error
p.add_argument('--wifi-mac',type=mac_argument,metavar='MAC',help='this handset\'s device Wi-Fi MAC; colons optional; prompted if omitted')
images=p.add_mutually_exclusive_group()
images.add_argument('--last-phone-good',action='store_true',help='use the archived earlier kernel/root instead of the current Wi-Fi fixes')
images.add_argument('--kernel',type=Path,help='override the current prebuilt kernel with a rebuilt kernel')
options=p.parse_args()
while options.wifi_mac is None:
 try:options.wifi_mac=validate_mac(input('Enter this Renoir\'s Wi-Fi MAC. (colons optional: AABBCCDDEEFF or AA:BB:CC:DD:EE:FF) Do NOT be lazy and reuse another MAC, boot a ROM and note your Renoir\'s MAC: '))
 except ValueError as error:print(str(error)+'. Please try again.',flush=True)
 except EOFError:p.error('A device Wi-Fi MAC is required; enter it at the prompt or pass --wifi-mac')
 except KeyboardInterrupt:raise SystemExit('\nBoot cancelled before contacting the phone.') from None
payload='recovery/assets/'+('renoir-phone-good-share.bin' if options.last_phone_good else 'renoir-ios-share.bin')
fb=os.environ.get('FASTBOOT') or next((str(p) for p in [Path('C:/platform-tools/fastboot.exe'),Path('/mnt/c/platform-tools/fastboot.exe')] if p.is_file()),None) or shutil.which('fastboot')
if not fb:raise SystemExit('Install platform-tools or set FASTBOOT')
def file(p):
 p=str(R/p)
 return subprocess.check_output(['wslpath','-w',p],text=True).strip() if fb.endswith('.exe') and os.name!='nt' else p
def cmd(*args,serial=None,timeout=30,live=False):
 command=[fb]+(['-s',serial] if serial else [])+list(args)
 try:
  return subprocess.run(command,capture_output=not live,text=True,timeout=timeout,check=True)
 except subprocess.CalledProcessError as error:
  detail='\n'.join(part.strip() for part in (error.stdout,error.stderr) if part and part.strip())
  raise SystemExit('fastboot '+args[0]+' failed (exit '+str(error.returncode)+').\n'+
                   (detail or 'See the fastboot error printed above. No kernel was started by this failed command.')) from None
 except subprocess.TimeoutExpired:
  raise SystemExit('fastboot '+args[0]+' timed out after '+str(timeout)+' seconds. '
                   'The RAM boot did not complete; check the USB connection and retry from stock fastboot.') from None
def devices():return [parts[0] for line in cmd('devices').stdout.splitlines() if len(parts:=line.split())>=2 and parts[1]=='fastboot']
def check(serial,key,value):
 q=cmd('getvar',key,serial=serial)
 match=re.search(r'(?m)^\s*(?:\(bootloader\)\s*)?'+re.escape(key)+r':\s*(\S+)\s*$',q.stdout+q.stderr)
 if match is None or match[1]!=value:raise SystemExit('Wrong device: expected '+key+' '+value)
for p in ['userland/system.packfs',payload,'prebuilt/renoir/resident-usb.img']:
 if not (R/p).is_file():raise SystemExit('Run recovery/restore.py first: missing '+p)
# Validate local inputs before changing the phone's boot state.
try:
 mac=options.wifi_mac
 kernel_path=options.kernel or R/'prebuilt/mach.development.bcm2837'
 kernel=None if options.last_phone_good else kernel_path.read_bytes()
 data=prepare((R/payload).read_bytes(),time.time(),wifi_mac=mac,kernel=kernel,
              cpu_count=None if options.last_phone_good else 8)
except (OSError,ValueError) as error:raise SystemExit(str(error))
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
print(f'Uploading system RAM image ({(R/"userland/system.packfs").stat().st_size/1e9:.2f} GB; fastboot progress follows)...',flush=True)
cmd('stage',file('userland/system.packfs'),serial=s,timeout=900,live=True)
# Refresh time after the large system upload; keep archived release assets intact.
data=prepare(data,time.time())
(R/'recovery/assets/run-current.bin').write_bytes(data)
print('Uploading kernel/root payload...',flush=True)
cmd('stage',file('recovery/assets/run-current.bin'),serial=s,timeout=180,live=True)
cmd('oem','run',serial=s);print('iOS started from RAM. No partition was flashed or erased.')
