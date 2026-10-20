#!/usr/bin/env python3
"""Exercise the actual SPMI writer: owner/PPID guards and one-byte encoding."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1];s=(r/'xnu/files/bsd/dev/renoir_haptic.c').read_text()
a=s.index('static bool rh_put(');b=s.index('static const struct rhh_bus rh_bus',a)
fn=s[a:b].replace('__asm__ volatile("dsb sy");','__sync_synchronize();')
code=r"""
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include "renoir_haptic_core.h"
typedef uintptr_t vm_offset_t;
#define NSEC_PER_USEC 1000
static uint32_t core[0x1100/4],owner[0x1000/4],write0[0x1000/4],write1[0x1000/4];
static uintptr_t rh_core=(uintptr_t)core,rh_owner=(uintptr_t)owner,rh_channel_write[2]={(uintptr_t)write0,(uintptr_t)write1};
static unsigned rh_channels[2]={129,130},mode,reads,ticks,locks,unlocks;
static bool rh_can_write=true,rh_leaving;
static uint32_t rh_read32(vm_offset_t a){
 if(a==(uintptr_t)write0+8 || a==(uintptr_t)write1+8){reads++;return mode==0?1:mode==1?5:mode==2?0:mode==3?9:reads==1?9:1;}
 return *(uint32_t *)a;
}
static void nanoseconds_to_absolutetime(uint64_t n,uint64_t *t){*t=n/1000;}
static uint64_t mach_absolute_time(void){return ticks++;}
static void redwood_spmi_lock(void){locks++;}
static void redwood_spmi_unlock(void){unlocks++;}
"""+fn+r"""
int main(void){
 core[(0x900+4*129)/4]=0x3f0<<8;core[(0x900+4*130)/4]=0x3f1<<8;
 assert(!rh_put(0xf246,0x80));assert(!rh_put(0x7142,1));assert(!locks);
 rh_can_write=false;assert(!rh_put(0xf048,33));rh_can_write=true;assert(!locks);
 owner[(0x700+4*129)/4]=3;assert(!rh_put(0xf048,33));owner[(0x700+4*129)/4]=0;assert(!locks);
 core[(0x900+4*129)/4]=0x3f2<<8;assert(!rh_put(0xf048,33));core[(0x900+4*129)/4]=0x3f0<<8;assert(!locks);
 assert(rh_put(0xf048,33));assert(write0[0]==0x480 && write0[4]==33);assert(locks==unlocks);
 for(unsigned i=0;i<0x1000/4;i++)if(i!=0 && i!=4)assert(write0[i]==0);
 assert(rh_put(0xf134,0x12));assert(write1[0]==0x340 && write1[4]==0x12);
 for(mode=1;mode<4;mode++){reads=ticks=0;assert(!rh_put(0xf04c,2));assert(locks==unlocks);assert(reads<=2001);}
 mode=4;reads=ticks=0;assert(rh_put(0xf04c,2));assert(reads==2);
}
"""
with tempfile.TemporaryDirectory(prefix='rh-spmi-write-') as d:
 p=Path(d);(p/'t.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined','-I'+str(r/'xnu/files/bsd/dev'),str(p/'t.c'),'-o',str(p/'t')],check=True)
 subprocess.run([str(p/'t')],check=True)
print('PM8350B SPMI writer: owner/PPID/allowlist guards, no BOOST/SDAM, byte encoding, timeout/denial/drop and lock release passed')
