#!/usr/bin/env python3
"""Cross-check real vendor CFA/tuning and execute the driver's AF initialization."""
from pathlib import Path
import hashlib, json, struct, subprocess, sys, tempfile
import camsensor
ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'xnu/files/bsd/dev/redwood_camera.c').read_text()
a = source.index('static void\naf_up(')
b = source.index('\n}', a) + 2
stub = r"""
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#define REDWOOD_CAMERA_NO_FOCUS 0xffffffffu
#define AF_CONTROL 2
#define AF_MODE 6
#define AF_TIMING 7
#define AF_POSITION 3
static unsigned sensors[4],*hw=&sensors[1];
static bool camera_renoir;
static unsigned af_position,writes,votes,reg[16],val[16],fail_at;
static bool af_write(unsigned r,unsigned v){assert(writes<16);reg[writes]=r;val[writes++]=v;return writes!=fail_at;}
static bool vaf(bool on){(void)on;votes++;return true;}
static void wait_ms(unsigned n){(void)n;}
static void af_look(const char*s){(void)s;}
static void say(const char*s,...){(void)s;}
"""
main = r"""
int main(void){
 camera_renoir=true;af_up(true);assert(writes==7 && votes==0 && af_position==300);
 assert(reg[4]==7 && val[4]==0x0b);
 writes=0;camera_renoir=false;af_up(true);assert(writes==7 && val[4]==7);
 writes=0;camera_renoir=true;fail_at=1;af_up(true);
 assert(writes==1 && votes==0 && af_position==REDWOOD_CAMERA_NO_FOCUS);
 for(fail_at=2;fail_at<=7;fail_at++){writes=0;af_up(true);assert(writes==fail_at && votes==0 && af_position==REDWOOD_CAMERA_NO_FOCUS);}
 puts("AF: native Renoir timing, Redwood isolation and every write failure passed; no unrelated rail vote");
}
"""
with tempfile.TemporaryDirectory() as tmp:
 d=Path(tmp);c=d/'af.c';c.write_text(stub+source[a:b]+main)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(c),'-o',str(d/'af')],check=True)
 subprocess.run([str(d/'af')],check=True)
 manifest=json.loads((ROOT/'tools/renoir-camera-tuning.json').read_text())
 for item in manifest:
  f=ROOT/'fw-camera/renoir'/Path(item['path']).name
  if not f.exists():
   print('SKIP vendor tuning checks: fetch_renoir_camera.py --tuning first');sys.exit(0)
  data=f.read_bytes()
  assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],f
  assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==item['git_blob'],f
  if f.name.endswith('.bin'):
   out=d/(f.stem+'.isp')
   subprocess.run([sys.executable,str(ROOT/'tools/camtuning.py'),str(f),str(out),'--lsc','lsc40'],check=True,stdout=subprocess.DEVNULL)
   assert out.read_bytes().startswith(b'RWCISP02')
 for name in ['renoir_ofilm_s5kgw3_wide','renoir_sunny_s5k3t2_front']:
  f=ROOT/'fw-camera/renoir'/('com.qti.sensormodule.'+name+'.bin')
  data=f.read_bytes();syms,order,pool=camsensor.symbols(data)
  sid=next(i for i in order if syms[i][0]=='resolutionData')
  _,offset,size=syms[sid];raw=data[pool+offset:pool+offset+size]
  assert size>0 and size%196==0
  assert all(struct.unpack_from('<I',raw,k)[0]==1 for k in range(0,size,196)),name
  if 's5kgw3_wide' in name:
   def values(i):return data[pool+syms[i][1]:pool+syms[i][1]+syms[i][2]]
   def mode_regs(m):
    words=struct.unpack_from('<49I',raw,196*m)
    return {r:v for r,v,*_ in camsensor.regsetting(data,pool,syms,values,words[24])}
   full,crop=mode_regs(1),mode_regs(7)
   assert full[0x0344]==0 and full[0x0346]==0 and full[0x0900]==0x0122
   assert full[0x034c]==4640 and full[0x034e]==3472
   assert crop[0x0344]>0 and crop[0x0346]>0 and crop[0x0900]==0x0111
   assert 0 <= (full[0x0348]+1)//2-full[0x034c] <= 32 # optical-black border
   assert 0 <= (full[0x034a]+1)//2-full[0x034e] <= 32
   print('GW3 native mode1: full sensor width, 2x2 binning, 4640x3472; mode7 is central 1:1 crop')
 print('Vendor profiles: five pinned blobs, four LSC40 exports, main/front native GBRG modes passed')
