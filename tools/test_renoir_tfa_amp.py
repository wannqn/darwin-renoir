#!/usr/bin/env python3
"""Fault-inject the actual volatile TFA startup and rollback, never touching a device."""
from pathlib import Path
import tempfile,subprocess
r=Path(__file__).resolve().parents[1]
code=r"""
#include <assert.h>
#include <stdio.h>
#include "renoir_tfa_amp_core.h"
static uint16_t regs[256],baseline[256];static unsigned calls,fail_at,writes;
static bool permanent,preparing;
static bool fail(void){calls++;return fail_at && (calls==fail_at || (permanent && calls>=fail_at));}
static bool rd(uint8_t addr,uint8_t reg,uint16_t *v){assert(addr==0x34);if(fail())return false;*v=regs[reg];return true;}
static bool wr(uint8_t addr,uint8_t reg,uint16_t v){
 assert(addr==0x34);assert(rtfa_write_allowed(reg)||reg==0x0f||reg==0xa0||reg==0xa1);
 assert(reg!=0xf0 && reg!=0xf5 && reg!=0xa3);if(reg==0xa1)assert(v==0);
 if(reg==0xf9)assert(!((v^baseline[reg])&~2u));
 if(reg==0){assert(!(v&0x1802));if(preparing)assert((v&1)&&!(v&8));}
 if(fail())return false;regs[reg]=v;writes++;return true;
}
static const struct rtfa_bus bus={rd,wr};
static struct renoir_tfa_plan plan={.address=0x34,.count=4,.fields={{0x0203,9},{0x20c3,2},{0x0040,1},{0xf910,1}}};
static void setup(void){memset(regs,0,sizeof(regs));regs[0]=0x4201;regs[3]=0xb73;regs[0xf0]=3;regs[0xf5]=6232;regs[0xfb]=0x1234;memcpy(baseline,regs,sizeof(regs));calls=writes=fail_at=0;permanent=false;preparing=true;}
static void preserved(void){assert(regs[0xf0]==3 && regs[0xf5]==6232);assert((regs[0]&1)&&!(regs[0]&8));}
int main(void){
 assert(rtfa_status_healthy(0x56,0x8044,0x810f,0x100,true)); /* actual muted idle */
 assert(rtfa_status_healthy(0x56,0xc044,0x810f,40,true)); /* active PWM */
 assert(rtfa_status_healthy(0x56,0xc044,0x810f,0x100,true)); /* observed active-PWM ADC transition is not a fault */
 assert(!rtfa_status_healthy(0x52,0xc044,0x810f,0x100,true)); /* real OTDS fault still trips with unavailable ADC */
 assert(!rtfa_status_healthy(0x56,0xc044,0x810f,81,true));
 for(unsigned b=0;b<16;b++) {
  if(0x54&(1u<<b))assert(!rtfa_status_healthy(0x56&~(1u<<b),0xc044,0x810f,40,true));
  if(0x10f&(1u<<b))assert(!rtfa_status_healthy(0x56,0xc044,0x810f&~(1u<<b),40,true));
  if(0x520&(1u<<b))assert(!rtfa_status_healthy(0x56|(1u<<b),0xc044,0x810f,40,true));
 }
 assert(!rtfa_status_healthy(0x56,0xc004,0x810f,40,true)); /* PLL lost */
 setup();struct rtfa_amp a={.address=0x34};assert(rtfa_prepare(&a,&bus,&plan));unsigned path_calls=calls;preserved();
 preparing=false;assert(rtfa_power(&a,&bus,true));assert(!(regs[0]&1)&&(regs[0]&8));
 assert(rtfa_shutdown(&a,&bus));preserved();
 for(unsigned i=1;i<=path_calls;i++){
  setup();a=(struct rtfa_amp){.address=0x34};fail_at=i;assert(!rtfa_prepare(&a,&bus,&plan));
  fail_at=0;preparing=false;assert(rtfa_shutdown(&a,&bus));preserved();
  for(unsigned reg=0;reg<256;reg++)if(reg!=0x0f && reg!=0xa0 && reg!=0xa1)assert(regs[reg]==baseline[reg]);
 }
 setup();regs[0]=0x4208;a=(struct rtfa_amp){.address=0x34};assert(!rtfa_prepare(&a,&bus,&plan)&&!writes);
 setup();a=(struct rtfa_amp){.address=0x34};assert(!rtfa_write(&a,&bus,0xf5,0));assert(!rtfa_write(&a,&bus,0xa3,1));
 assert(!rtfa_write(&a,&bus,0xf9,0xffff));assert(!writes);
 setup();a=(struct rtfa_amp){.address=0x34};assert(rtfa_prepare(&a,&bus,&plan));preparing=false;assert(rtfa_power(&a,&bus,true));
 permanent=true;fail_at=calls+1;assert(!rtfa_shutdown(&a,&bus)); /* wrapper must assert shared reset */
 printf("TFA amp: %u injected preparation failures, write allowlist, forced powerdown, OTP/calibration preservation and rollback passed\n",path_calls);
}
"""
with tempfile.TemporaryDirectory(prefix='tfa-amp-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined','-I'+str(r/'xnu/files/bsd/dev'),str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
