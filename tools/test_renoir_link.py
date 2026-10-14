#!/usr/bin/env python3
"""Run actual link probe with fake registers: GPIO order, bounded wait, restore."""
from pathlib import Path
import subprocess
import tempfile
src = (Path(__file__).resolve().parents[1] / 'xnu/files/bsd/dev/redwood_wifi.c').read_text()
start = src.index('static bool\nrenoir_pcie_link_probe(')
end = src.index('/* Probe 6/7', start)
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
static uint32_t p[0x4000/4],d[0x4000/4],g[0x61000/4];
static unsigned scenario,time_us,wlan_time,perst_time;
static void say(const char *s,...) { (void)s; }
static void renoir_bhi_host(vm_offset_t p,vm_offset_t t) { (void)p;(void)t;assert(0); }
static void renoir_bhi_cleanup(bool f) { (void)f;assert(0); }
static bool renoir_pcie_config_probe(vm_offset_t d,unsigned p) { (void)d;(void)p; assert(0); return false; }
static void sleep_us(unsigned n) { time_us+=n;assert(time_us<400000); }
static uint32_t rd(vm_offset_t a) { return *(uint32_t *)a; }
static void wr(vm_offset_t a,uint32_t v) {
 *(uint32_t *)a=v;
 if(a==(uintptr_t)&g[(64*0x1000+4)/4] && v==2) wlan_time=time_us;
 if(a==(uintptr_t)&g[(94*0x1000+4)/4] && v==2) {
  assert(wlan_time && time_us-wlan_time>=10000);perst_time=time_us;
 }
 if(a==(uintptr_t)&p[0x1b0/4] && (v&0x100)) {
  assert(perst_time && time_us-perst_time>=100000);
  if(!scenario) { d[0xf28/4]=0x400;d[0x80/4]|=0x20110000; }
 }
}
''' + src[start:end].replace('__asm__ volatile("dsb sy" ::: "memory");', '(void)0;') + r'''
int main(void) {
 for(scenario=0;scenario<2;scenario++) {
  memset(p,0,sizeof(p));memset(d,0,sizeof(d));memset(g,0,sizeof(g));
  time_us=wlan_time=perst_time=0;
  g[64*0x1000/4]=1; d[0x80c/4]=0xaabb;d[0x90/4]=3;d[0x80/4]=3;d[0x70c/4]=0x123;
  bool ok=renoir_pcie_link_probe((uintptr_t)p,(uintptr_t)d,(uintptr_t)g,11);
  assert(ok==!scenario);
  assert(g[64*0x1000/4]==1 && g[(64*0x1000+4)/4]==0 && g[(94*0x1000+4)/4]==0);
  assert(p[0x1b0/4]==0 && d[0x80c/4]==0xaabb && d[0x90/4]==3 && d[0x80/4]==3 && d[0x70c/4]==0x123);
 }
 puts("Renoir PCIe link: WLAN_EN/PERST timing, success/timeout and register restoration passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-link-') as tmp:
    p = Path(tmp)
    (p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
