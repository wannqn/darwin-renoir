#!/usr/bin/env python3
"""Exercise real RPMh read code: no write packets, bounded wait, restore slot."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
src = (root / 'xnu/files/bsd/dev/redwood_wifi.c').read_text()
start = src.index('static bool\nrenoir_rpmh_read_locked(')
end = src.index('\nstatic void\nrenoir_wifi_vote_survey', start)
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef uintptr_t vm_offset_t;
#define RSC_ID 0
#define RSC_TCS(n) (0xd00+672*(n))
#define TCS_STATUS 0x18
#define TCS_CONTROL 0x14
#define TCS_ENABLED 0x1c
#define TCS_COMMAND(n) (0x30+20*(n))
struct cmd_db_entry { uint32_t address; };
static uint32_t regs[0x10000/4];
static struct { vm_offset_t base; } rsc;
static struct cmd_db_entry resource={.address=0x41a00};
static unsigned scenario,writes,sleeps,requests,locked;
static void redwood_rpmh_lock(void){assert(!locked);locked=1;}
static void redwood_rpmh_unlock(void){assert(locked);locked=0;}
static const struct cmd_db_entry *rpmh_resource(const char *n,uint32_t a) { (void)n;(void)a;return &resource; }
static void need(void *b) { (void)b; }
static void say(const char *s,...) { (void)s; }
static void sleep_us(unsigned n) { (void)n;sleeps++;assert(sleeps<=2000); }
static uint32_t rd(vm_offset_t a) { return *(uint32_t *)a; }
static void wr(vm_offset_t a,uint32_t v) {
 writes++; *(uint32_t *)a=v;
 vm_offset_t t=rsc.base+RSC_TCS(0);
 if(a==t+8) { *(uint32_t *)(t+4)=0; }
 if(a==t+TCS_CONTROL && (v&(1u<<24))) {
  requests++; assert(rd(t+0x30)==0x108); /* no WRITE flag */
  assert(rd(t+0x34)==resource.address+4);
  if(scenario!=2) { *(uint32_t *)(t+4)=1; }
  *(uint32_t *)(t+0x3c)=scenario==3 ? 0x100 : 0x10100;
  *(uint32_t *)(t+0x40)=0x1234;
 }
}
''' + src[start:end].replace('__asm__ volatile("dsb sy" ::: "memory");', '(void)0;') + r'''
int main(void) {
 rsc.base=(uintptr_t)regs;
 for(scenario=0;scenario<5;scenario++) {
  memset(regs,0,sizeof(regs)); writes=sleeps=requests=0;
  unsigned t=RSC_TCS(0)/4;
  regs[t+0x18/4]=scenario==1 ? 0 : 1;
  regs[0]=scenario==4 ? 3u<<16 : 0;
  static const unsigned offsets[]={0,0x10,0x14,0x1c,0x30,0x34,0x38};
  uint32_t saved[7];
  for(unsigned i=0;i<7;i++) { saved[i]=regs[t+offsets[i]/4]=i+0x100; }
  uint32_t result=0xdeadbeef;
  bool ok=renoir_rpmh_read("ldob6",4,&result);
  assert(ok==(scenario==0));
  assert(!locked);
  assert(result==(ok ? 0x1234 : 0xdeadbeef));
  assert(requests==((scenario==1 || scenario==4) ? 0 : 1));
  if(scenario==1 || scenario==4) { assert(writes==0); }
  for(unsigned i=0;i<7;i++) { assert(regs[t+offsets[i]/4]==saved[i]); }
 }
 puts("Renoir RPMh read: read packets only, busy/timeout/error handling and slot restoration passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-rpmh-') as tmp:
    p = Path(tmp)
    (p / 'test.c').write_text(code)
    subprocess.run(['clang', '-Wall', '-Wextra', '-fsanitize=address,undefined',
                    str(p / 'test.c'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)
