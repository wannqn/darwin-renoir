#!/usr/bin/env python3
"""Exercise BAR mapping without DMA, including hostile MHI BHI offsets."""
from pathlib import Path
import subprocess
import tempfile
src=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_wifi.c').read_text()
a=src.index('static bool\nrenoir_pcie_mhi_survey(')
b=src.index('static bool\nrenoir_pcie_config_probe(',a)
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
static uint32_t d[0x4000/4],c[0x4000/4],bar[0x10000/4];
static unsigned scenario,writes,bar_reads;
static void say(const char *s,...) { (void)s; }
static bool renoir_bhi_load(vm_offset_t b,vm_offset_t c,vm_offset_t d,unsigned p) { (void)b;(void)c;(void)d;(void)p;assert(0);return false; }
static void sleep_us(unsigned n) { (void)n; }
static vm_offset_t ml_io_map(vm_offset_t p,vm_offset_t n) {
 assert(p==0x60400000 && n==sizeof(bar));return (uintptr_t)bar;
}
static uint32_t rd(vm_offset_t p) {
 if(p>=(uintptr_t)bar && p<(uintptr_t)(bar+sizeof(bar)/4)) {
  bar_reads++;assert((c[1]&6)==2 && c[4]==0x60400004 && c[5]==0);
  assert(d[0x20/4]==0x60506040 && (d[1]&2));
  assert(d[0x1200/4]==0 && d[0x1208/4]==0x60400000 && d[0x1210/4]==0x605fffff);
 }
 return *(uint32_t *)p;
}
static void wr(vm_offset_t p,uint32_t v) {
 writes++;
 if(p>=(uintptr_t)c && p<(uintptr_t)(c+sizeof(c)/4)) {
  assert(p==(uintptr_t)&c[1] || p==(uintptr_t)&c[4] || p==(uintptr_t)&c[5]);
  if(p==(uintptr_t)&c[1]) assert(!(v&4)); /* never enable bus mastering */
 } else assert(p>=(uintptr_t)d && p<(uintptr_t)(d+sizeof(d)/4));
 if(scenario==3 && p==(uintptr_t)&d[0x1204/4]) v&=~(1u<<31);
 *(uint32_t *)p=v;
}
''' + src[a:b].replace('__asm__ volatile("dsb sy" ::: "memory");','(void)0;') + r'''
int main(void) {
 for(scenario=0;scenario<4;scenario++) {
  memset(d,0,sizeof(d));memset(c,0,sizeof(c));memset(bar,0,sizeof(bar));writes=bar_reads=0;
  d[0x80/4]=1u<<29;d[0xf28/4]=0x400;d[0x20/4]=0x123;d[1]=1;
  c[1]=scenario==2 ? 4 : 0;c[4]=4;c[5]=0x123;
  bar[0x28/4]=scenario==1 ? 0xfffffffc : 0x1000;
  uint32_t saved[7];for(unsigned i=0;i<7;i++) saved[i]=d[(0x1200+4*i)/4]=i+10;
  bool ok=renoir_pcie_mhi_survey((uintptr_t)d,(uintptr_t)c,13);
  assert(ok==(scenario==0));
  assert(c[1]==(scenario==2 ? 4u : 0u) && c[4]==4 && c[5]==0x123);
  assert(d[1]==1 && d[0x20/4]==0x123);
  for(unsigned i=0;i<7;i++) assert(saved[i]==d[(0x1200+4*i)/4]);
  if(scenario==2 || scenario==3) assert(bar_reads==0);
  if(scenario==2) assert(writes==0);
 }
 puts("Renoir MHI survey: BAR bounds, bus mastering disabled, timeout and complete config restoration passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-mhi-survey-') as tmp:
    p=Path(tmp);(p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
