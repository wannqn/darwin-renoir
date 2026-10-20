#!/usr/bin/env python3
"""Compile the real probe transfer against a simulated PMIC observer channel."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/renoir_haptic.c').read_text();a=s.index('static bool rh_read(');b=s.index('static bool rh_get',a)
fn=s[a:b].replace('__asm__ volatile("dsb sy");','__sync_synchronize();')
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
#define NSEC_PER_USEC 1000
static uint32_t mem[0x10000/4];
static vm_offset_t rh_observer;
static bool rh_leaving;
static unsigned mode,reads,locks,unlocks,ticks;
static void nanoseconds_to_absolutetime(uint64_t n,uint64_t *v){*v=n/1000;}
static uint64_t mach_absolute_time(void){return ticks++;}
static void redwood_spmi_lock(void){locks++;}
static void redwood_spmi_unlock(void){unlocks++;}
static uint32_t rh_read32(vm_offset_t p){
 unsigned off=(unsigned)(p-rh_observer)%0x80;
 if(off==8){reads++;return mode==0?1:mode==1?5:mode==2?3:mode==3?9:mode==4?0:reads==1?9:1;}
 if(off==0x18)return 0x44332211;if(off==0x1c)return 0x88776655;assert(0);return 0;
}
"""+fn+r"""
int main(void){
 rh_observer=(uintptr_t)mem;uint8_t out[8];
 memset(mem,0xa5,sizeof(mem));
 assert(!rh_read(512,0,out,1));assert(!rh_read(3,0,out,0));assert(!rh_read(3,255,out,2));assert(!locks);
 assert(rh_read(3,0x46,out,8));assert(!memcmp(out,"\x11\x22\x33\x44\x55\x66\x77\x88",8));
 assert(mem[(3*0x80)/4]==((1u<<27)|(0x46<<4)|7));
 for(unsigned i=0;i<sizeof(mem)/4;i++)if(i!=3*0x80/4)assert(mem[i]==0xa5a5a5a5);
 for(mode=1;mode<=4;mode++){reads=0;ticks=0;assert(!rh_read(3,0x46,out,1));assert(locks==unlocks);assert(reads<=2001);}
 mode=5;reads=0;assert(rh_read(3,0x46,out,1));assert(reads==2);assert(locks==unlocks);
 mode=3;reads=0;assert(!rh_read(3,0x46,out,1));assert(reads==3);
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-haptic-probe-') as d:
 p=Path(d);(p/'t.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'t.c'),'-o',str(p/'t')],check=True)
 subprocess.run([str(p/'t')],check=True)
print('Renoir haptic observer: bounds, read command only, timeout/denial/failure, bounded dropped retries and lock release passed')
