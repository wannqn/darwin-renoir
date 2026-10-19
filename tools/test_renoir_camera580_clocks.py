#!/usr/bin/env python3
"""Run actual camera PLL code; check shima constants and state rollback."""
from pathlib import Path
import subprocess
import tempfile
repo=Path(__file__).resolve().parents[1]
s=(repo/'xnu/files/bsd/dev/redwood_camera.c').read_text()
a=s.index('#define PLL_MODE ');b=s.index('/* An RCG set',a)
pll=s[a:b].replace('__asm__ volatile("dsb sy" ::: "memory");','')
code=r'''#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
static uint32_t regs[128];
static unsigned writes,fail;
static bool camera_renoir=true,timeout;
static const unsigned camcc=0;
static uint32_t rd(unsigned r){assert(r<sizeof(regs));return regs[r/4];}
static void wr(unsigned r,uint32_t v){assert(r<sizeof(regs));if(++writes==fail)return;regs[r/4]=v;if(r==0x38 && v==1)regs[0]|=1u<<31;}
static void give_up(const char*s){(void)s;}
static int say(const char*s,...){(void)s;return 0;}
static bool wait_bits(unsigned r,uint32_t mask,uint32_t want,unsigned us){(void)us;return !timeout && (rd(r)&mask)==want;}
'''+pll+r'''
static void setup(void){
 memset(regs,0,sizeof(regs));writes=0;fail=0;timeout=false;pll_on=false;
 for(unsigned i=1;i<sizeof(renoir_pll_regs)/sizeof(renoir_pll_regs[0]);i++)regs[renoir_pll_regs[i]/4]=0x100+i;
 regs[0x38/4]=0;
}
int main(void){
 setup();uint32_t old[128];memcpy(old,regs,sizeof(old));
 assert(pll0_up());assert(regs[0x20/4]==0x2a9a699c && regs[0x2c/4]==0x01800000);
 assert(!(regs[0]&(1u<<23)));unsigned n=writes;pll0_down();
 assert(memcmp(old,regs,sizeof(old))==0);
 for(unsigned f=1;f<=n;f++){
  setup();memcpy(old,regs,sizeof(old));fail=f;(void)pll0_up();fail=0;pll0_down();
  assert(memcmp(old,regs,sizeof(old))==0);
 }
 setup();memcpy(old,regs,sizeof(old));timeout=true;assert(!pll0_up());pll0_down();assert(memcmp(old,regs,sizeof(old))==0);
 setup();regs[0]=1;assert(!pll0_up());assert(writes==0);
 setup();regs[0x38/4]=1;assert(!pll0_up());assert(writes==0);
 setup();regs[0xc/4]|=1u<<21;assert(!pll0_up());assert(writes==0);
 puts("Titan580 clocks: actual PLL0 5LPE values, full register rollback at every setup write/lock timeout and busy refusal passed");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
