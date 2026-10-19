#!/usr/bin/env python3
"""Execute shared CSID480/580 setup and actual RSC IRQ address adapters."""
from pathlib import Path
import subprocess
import tempfile
repo=Path(__file__).resolve().parents[1];s=(repo/'xnu/files/bsd/dev/redwood_camera.c').read_text()
def function(name):
 start=s.rfind('static ',0,s.index('\n'+name+'('));b=s.index('{',start);end=b+1;depth=1
 while depth:
  depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[start:end].replace('__asm__ volatile("dsb sy" ::: "memory");','')
a=s.index('#define CSID_HW_VERSION');b=s.index('/*\n * A line',a)
code=r'''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
typedef uintptr_t vm_offset_t;
static uint32_t regs[0x2000/4];
static unsigned writes,fail,last_address,last_value;
static vm_offset_t csid,rsc;
static bool camera_renoir=true,csid_running,tpg_running;
#define CAMERA_TCS 1
#define RSC_TCS_BASE 0xd00
#define RSC_IRQ_CLEAR 0xd08
static uint32_t rd(uintptr_t r){assert(!(r&3)&&r<sizeof(regs));return regs[r/4];}
static void wr(uintptr_t r,uint32_t v){assert(!(r&3)&&r<sizeof(regs));last_address=r;last_value=v;regs[r/4]=v;}
static void spin_us(unsigned u){(void)u;}
static bool blk_put(uintptr_t base,const char*n,uint32_t r,uint32_t v,bool check){(void)n;(void)check;if(++writes==fail)return false;wr(base+r,v);return true;}
static bool wait_reg(uintptr_t b,uint32_t r,uint32_t mask,uint32_t want,unsigned u){(void)b;(void)r;(void)mask;(void)want;(void)u;return true;}
static int say(const char*s,...){(void)s;return 0;}
static void give_up(const char*s){(void)s;}
'''+s[a:b]+'\n'+'\n'.join(function(n) for n in ['csid_reset','csid_config','tpg_start','rcam_arc_get','rcam_arc_put','rcam_arc_wait'])+r'''
int main(void){
 assert(csid_reset());writes=0;
 assert(csid_config(5,4,0x3210,0,1280,720,false));
 assert(regs[0x100/4]==((5u<<20)|(0x3210<<4)|3));
 assert(regs[0x104/4]==65 && (regs[0x200/4]&(1u<<31)));
 unsigned n=writes;
 for(unsigned f=1;f<=n;f++){writes=0;fail=f;assert(!csid_config(5,4,0x3210,0,1280,720,false));}
 fail=0;assert(csid_config(-1,4,0x3210,10,1600,1200,false));
 assert((regs[0x104/4]&4) && regs[0x610/4]==((1600u<<16)|1200));
 assert(tpg_start()&&tpg_running&&csid_running);
 regs[0xd00/4]=0xa5;
 assert(rcam_arc_get((void*)0xfa0,0)==0);
 assert(rcam_arc_put((void*)0xfa0,0,1,false));assert(regs[0xd00/4]==0xa7);
 assert(rcam_arc_put((void*)0xfa0,0,0,false));assert(regs[0xd00/4]==0xa5);
 assert(rcam_arc_put((void*)0xfa0,8,1,false));assert(last_address==0xd08&&last_value==2);
 regs[0xd04/4]=2;assert(rcam_arc_get((void*)0xfa0,4)==1);
 assert(rcam_arc_wait((void*)0xfa0,4,1,1,10));
 assert(rcam_arc_put((void*)0xfa0,0x34,0x30000,false));assert(last_address==0xfd4);
 puts("Titan580 CSID: PHY5 selector, RAW10, full-width TPG VC, setup failures and RSC shared IRQ1 mapping passed");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
