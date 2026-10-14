#!/usr/bin/env python3
"""Exercise actual SMMU setup/rollback with no DMA or physical registers."""
from pathlib import Path
import re
import subprocess
import tempfile
src=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_wifi.c').read_text()
clean=re.sub(r'/\*.*?\*/','',src,flags=re.S)
defines='\n'.join(line for line in clean.splitlines() if re.match(r'#define (SMMU_|RADIO_STREAM|RADIO_ADDRESSES|PTE_ADDRESS)',line))
a=src.index('static bool\nradio_space_on_for(')
b=src.index('/*\n * For the driver (redwood_lx.c): memory',a)
c=src.index('static void\nrenoir_wifi_smmu_probe(')
e=src.index('static void\nrenoir_wifi_init(void)',c)
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
struct block { vm_offset_t base; };
static uint32_t g[0x2000/4],s[0x1000/4],cb[0x1000/4];
static struct block apps_smmu,apps_smmu_second,apps_smmu_context;
static struct { unsigned match,context,old_smr,old_s2cr,old_sctlr;vm_offset_t tables;bool on; } radio_space;
static unsigned scenario,writes,pause_ms,step;
static void say(const char *s,...) { (void)s; }
static void sleep_ms(unsigned n) { (void)n; }
static uint64_t kvtophys(vm_offset_t v) { (void)v;return 0x100000; }
static void radio_space_faults(void) {}
static bool radio_space_find(void) {
 radio_space.match=1;radio_space.context=2;radio_space.old_smr=g[0x804/4];
 radio_space.old_s2cr=g[0xc04/4];radio_space.old_sctlr=cb[0];return true;
}
static bool radio_enter(uint64_t a,uint64_t p,uint64_t n) { (void)a;(void)p;(void)n;return true; }
static uint32_t rd(vm_offset_t a) { return *(uint32_t *)a; }
static void wr(vm_offset_t a,uint32_t v) {
 writes++;
 if(a==(uintptr_t)&cb[0x58/4]) return; /* W1C fault status */
 if(scenario==2 && a==(uintptr_t)&g[0x804/4] && (v>>31)) return; /* TZ refuses SMR */
 *(uint32_t *)a=v;
}
static uint32_t get(struct block *b,const char *n,unsigned o) { (void)n;return rd(b->base+o); }
static void put(struct block *b,const char *n,unsigned o,uint32_t v) { (void)n;wr(b->base+o,v); }
''' + defines + '\n' + src[a:b] + src[c:e].replace('__asm__ volatile("dsb sy" ::: "memory");','(void)0;') + r'''
int main(void) {
 apps_smmu.base=(uintptr_t)g;apps_smmu_second.base=(uintptr_t)s;apps_smmu_context.base=(uintptr_t)cb;
 for(scenario=0;scenario<4;scenario++) {
  memset(g,0,sizeof(g));memset(s,0,sizeof(s));memset(cb,0,sizeof(cb));memset(&radio_space,0,sizeof(radio_space));
  g[0x20/4]=4;g[0x800/4]=scenario==1 ? 0x80012400 : 0x80001c00;
  cb[0x10/4]=0x123;cb[0x20/4]=0x456;cb[0x30/4]=0x789;s[8/4]=0x11000;s[0x808/4]=0;
  cb[0x58/4]=scenario==3 ? 4 : 0x400; /* reserved bit is not a pending fault */
  uint32_t gs[sizeof(g)/4],ss[sizeof(s)/4];memcpy(gs,g,sizeof(g));memcpy(ss,s,sizeof(s));
  uint32_t saved_cb[9];unsigned offsets[]={0,0x10,0x20,0x24,0x28,0x2c,0x30,0x38,0x3c};
  for(unsigned i=0;i<9;i++) saved_cb[i]=cb[offsets[i]/4];
  writes=0;renoir_wifi_smmu_probe();assert(!radio_space.on);
  assert(!memcmp(gs,g,sizeof(g)) && !memcmp(ss,s,sizeof(s)));
  for(unsigned i=0;i<9;i++) assert(cb[offsets[i]/4]==saved_cb[i]);
  if(scenario==3) assert(writes==0);
 }
 writes=0;assert(!radio_space_on_for(0x8000,0));assert(writes==0);
 (void)radio_space_on; /* redwood wrapper is compiled too */
 puts("Renoir SMMU: overlap refusal, TZ refusal, empty context setup and full configuration rollback passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-smmu-') as tmp:
    p=Path(tmp);(p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
