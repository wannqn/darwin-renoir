#!/usr/bin/env python3
"""Execute actual early DMA reservation/consumption code with host VM stubs."""
from pathlib import Path
import re, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'xnu/files/bsd/dev/redwood_lx.c').read_text()
a=s.index('#define RENOIR_LX_POOL_BYTES');b=s.index('void *\nlx_os_map_registers',a)
code=s[a:b]
# The host has no ARM cache-maintenance instructions; leave all control flow intact.
code=re.sub(r'__asm__ volatile\s*\([^;]+;', '(void)0;',code)
stub=r"""
#include <stdint.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef uintptr_t vm_offset_t;
#define KERN_SUCCESS 0
#define KMA_KOBJECT 1
#define KMA_ZERO 2
#define KMA_DATA 4
#define VM_KERN_MEMORY_IOKIT 0
#define VM_WIMG_WCOMB 0
#define round_page(n) (((n)+4095ul)&~4095ul)
#define bzero(p,n) memset(p,0,n)
static int kernel_map;
static bool renoir=true,fail;
static unsigned allocations,mappings,radio_maps;
static void *owned[8];
static bool redwood_board_is(const char *n){return renoir && !strcmp(n,"renoir");}
static void say(const char *s,...){(void)s;}
static int kmem_alloc_contig(int map,vm_offset_t *p,unsigned long bytes,int a,int b,int c,int f,int t){
 (void)map;(void)a;(void)b;(void)c;(void)f;(void)t;
 if(fail)return 1;
 assert(allocations<8);owned[allocations]=malloc(bytes);assert(owned[allocations]);*p=(uintptr_t)owned[allocations++];return 0;
}
static uint64_t kvtophys(vm_offset_t p){return p;}
static vm_offset_t ml_io_map_unmappable(uint64_t p,unsigned long n,int f){(void)n;(void)f;mappings++;return p;}
static bool redwood_wifi_radio_map(uint64_t p,unsigned long n,unsigned long long *a){(void)n;radio_maps++;*a=p;return true;}
"""
pool_macro=next(l for l in (root/'wifi/lx/src/lx_base.c').read_text().splitlines() if l.startswith('#define POOL_SIZE'))
stub += "\nstatic int lx_os_radio_model(void){return renoir ? 1 : 0;}\n"+pool_macro+"\n"
main=r"""
int main(void){
 unsigned long long dma;
 assert(POOL_SIZE==RENOIR_LX_POOL_BYTES);
 renoir=false;lx_reserve_radio_pool();assert(!allocations && !mappings && !radio_maps);
 renoir=true;lx_reserve_radio_pool();uintptr_t saved=lx_early_pool;
 assert(saved && allocations==1 && !mappings && !radio_maps);
 lx_reserve_radio_pool();assert(allocations==1 && lx_early_pool==saved);
 void *other=lx_os_radio_memory(4096,&dma);assert(other && allocations==2 && lx_early_pool==saved);
 void *pool=lx_os_radio_memory(RENOIR_LX_POOL_BYTES,&dma);
 assert((uintptr_t)pool==saved && dma==saved && !lx_early_pool && allocations==2 && mappings==2 && radio_maps==2);
 fail=true;assert(!lx_os_radio_memory(RENOIR_LX_POOL_BYTES,&dma));
 lx_reserve_radio_pool();assert(!lx_early_pool && allocations==2);
 fail=false;pool=lx_os_radio_memory(4096,&dma);assert(pool && allocations==3);
 for(unsigned i=0;i<allocations;i++)free(owned[i]);
 puts("Wi-Fi pool: Renoir-only early reservation, no early SMMU mapping, idempotence, exact-size single consumption and allocation failure fallback passed");
}
"""
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(stub+code+main)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
