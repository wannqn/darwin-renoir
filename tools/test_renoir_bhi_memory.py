#!/usr/bin/env python3
"""Execute the actual BHI reservation/consumption code without device mappings."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'xnu/files/bsd/dev/renoir_mhi_boot.h').read_text()
code = source[source.index('static vm_offset_t renoir_bhi_early_buffer;'):source.index('static struct {')]
program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
typedef uintptr_t vm_offset_t;
#define RENOIR_BHI_SIZE 0x80000u
#define round_page(n) (((n)+16383u)&~16383u)
#define kernel_map 0
#define KERN_SUCCESS 0
#define KMA_KOBJECT 1
#define KMA_ZERO 2
#define KMA_DATA 4
#define VM_KERN_MEMORY_IOKIT 0
static bool fail;
static unsigned allocations;
static void *owned[4];
static void say(const char *format, ...) { (void)format; }
static int kmem_alloc_contig(int map,vm_offset_t *out,uint32_t size,int a,int b,int c,int flags,int tag) {
 (void)map;(void)a;(void)b;(void)c;(void)flags;(void)tag;
 if(fail) return 1;
 assert(allocations<4); owned[allocations]=calloc(1,size);assert(owned[allocations]);
 *out=(uintptr_t)owned[allocations++];return 0;
}
''' + code + r'''
int main(void) {
 renoir_bhi_reserve(0);renoir_bhi_reserve(0x800001);assert(!allocations);
 fail=true;renoir_bhi_reserve(0x500001);assert(!renoir_bhi_early_buffer);
 fail=false;renoir_bhi_reserve(0x500001);
 vm_offset_t saved=renoir_bhi_early_buffer,buffer=0;
 uint32_t size=round_page(0x500001)+0x10000+0x800000;
 assert(saved && renoir_bhi_early_size==size && allocations==1);
 renoir_bhi_reserve(0x500001);assert(allocations==1);
 assert(renoir_bhi_allocate(4096,&buffer));assert(allocations==2 && renoir_bhi_early_buffer==saved);
 fail=true;assert(renoir_bhi_allocate(size,&buffer));
 assert(buffer==saved && !renoir_bhi_early_buffer && !renoir_bhi_early_size && allocations==2);
 assert(!renoir_bhi_allocate(size,&buffer));
 for(unsigned i=0;i<allocations;i++)free(owned[i]);
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-bhi-memory-') as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(program)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('BHI memory: bounded/idempotent reservation, exact-size single consumption after fragmentation and fallback passed')
