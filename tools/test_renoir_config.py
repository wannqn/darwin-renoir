#!/usr/bin/env python3
"""Check endpoint config access guards and restore the host's translation."""
from pathlib import Path
import subprocess
import tempfile
src = (Path(__file__).resolve().parents[1] / 'xnu/files/bsd/dev/redwood_wifi.c').read_text()
start = src.index('static bool\nrenoir_pcie_config_probe(')
end = src.index('static bool\nrenoir_pcie_link_probe(', start)
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
static uint32_t dbi[0x4000/4],config[0x4000/4];
static unsigned scenario,mappings,reads,writes;
static void say(const char *s,...) { (void)s; }
static bool renoir_pcie_mhi_survey(vm_offset_t d,vm_offset_t c,unsigned p) { (void)d;(void)c;(void)p;assert(0);return false; }
static void sleep_us(unsigned n) { (void)n; }
static vm_offset_t ml_io_map(vm_offset_t pa,vm_offset_t size) {
 assert(pa==0x60100000 && size==0x4000); mappings++;return (uintptr_t)config;
}
static uint32_t rd(vm_offset_t a) {
 if(a>=(uintptr_t)config && a<(uintptr_t)(config+0x1000)) {
  assert(scenario!=1 && scenario!=3);reads++;
  assert(dbi[(0x1000+4)/4]&(1u<<31));
  assert(dbi[0x1000/4]==4 && dbi[0x1008/4]==0x60100000 && dbi[0x1010/4]==0x60100fff);
  assert(dbi[0x1014/4]==0x01000000 && (dbi[0x18/4]&0xffffff)==0x10100);
 }
 return *(uint32_t *)a;
}
static void wr(vm_offset_t a,uint32_t v) {
 assert(a>=(uintptr_t)dbi && a<(uintptr_t)(dbi+0x1000)); /* no endpoint writes, no bus mastering */
 writes++;*(uint32_t *)a=v;
 if(scenario==3 && a==(uintptr_t)&dbi[0x1004/4] && v==(1u<<31)) { dbi[0x80/4]=0; }
}
''' + src[start:end].replace('__asm__ volatile("dsb sy" ::: "memory");', '(void)0;') + r'''
int main(void) {
 for(scenario=0;scenario<4;scenario++) {
  memset(dbi,0,sizeof(dbi));memset(config,0,sizeof(config));mappings=reads=writes=0;
  dbi[0x80/4]=scenario==1 ? 0 : 1u<<29;dbi[0xf28/4]=0x400;dbi[0x18/4]=0x55110000;
  uint32_t saved[7];for(unsigned i=0;i<7;i++) { saved[i]=dbi[(0x1000+4*i)/4]=i+11; }
  config[0]=scenario==2 ? 0xffffffff : 0x110317cb;
  bool ok=renoir_pcie_config_probe((uintptr_t)dbi,12);
  assert(ok==(scenario==0));
  assert(mappings==(scenario==1 ? 0 : 1));
  assert(reads==(scenario==0 ? 4 : scenario==2 ? 1 : 0));
  assert(dbi[0x18/4]==0x55110000);
  for(unsigned i=0;i<7;i++) assert(dbi[(0x1000+4*i)/4]==saved[i]);
 }
 puts("Renoir PCIe config: link guards, CFG0 BDF, no endpoint writes and translation restoration passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-config-') as tmp:
    p = Path(tmp)
    (p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
