#!/usr/bin/env python3
"""Exercise real LX PCI window and coherent-pool code with ASan/UBSan."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[1]
bus=(root/'wifi/lx/src/lx_bus.c').read_text()
mem=(root/'wifi/lx/src/lx_base.c').read_text()
def function(source,name):
    end=source.index('\n{',source.index('\n'+name+'('))+2
    start=source.rfind('\nstatic ',0,end)
    if start<0: start=source.rfind('\nvoid *',0,end)
    depth=1;pos=end
    while depth:
        pos+=1
        depth+=(source[pos]=='{')-(source[pos]=='}')
    return source[start:pos+1]
state=bus[bus.index('static struct {'):bus.index('} bus;')+6]
pool=mem[mem.index('#define POOL_SIZE'):mem.index('static bool\nin_pool')]
alloc_start=mem.index('void *\nlinux_dma_alloc_coherent')
alloc_end=mem.index('\nvoid\nkmem_free',alloc_start)
code=r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
typedef uint8_t u8;typedef uint32_t u32;typedef unsigned spinlock_t;struct ath11k_base {void *mem;};
struct mutex { unsigned unused; };
#define CE_COUNT_MAX 12
#define ATH11K_EXT_IRQ_GRP_NUM_MAX 16
#define ATH11K_PCI_WINDOW_START 0x80000
#define ATH11K_PCI_WINDOW_RANGE_MASK 0x7ffff
#define ATH11K_PCI_WINDOW_ENABLE_BIT 0x40000000
#define ATH11K_PCI_WINDOW_REG_ADDRESS 0x310c
#define HAL_SEQ_WCSS_UMAC_OFFSET 0xa00000
#define HAL_SEQ_WCSS_UMAC_CE0_SRC_REG(ab) 0x1b80000
#define SAID_FIRST 600
#define roundup2(x,a) (((x)+(a)-1)&~((a)-1))
static unsigned model,offline,locked,selected,last_target,last_value,accesses;
static bool posted;
static unsigned char registers[0x200000];
static unsigned lx_os_radio_model(void){return model;}
static int lx_os_rproc_boot(void){return offline ? 6 : 0;}
static void spin_lock_bh(spinlock_t *s){(void)s;assert(!locked);locked=1;}
static void spin_unlock_bh(spinlock_t *s){(void)s;assert(locked);locked=0;}
static void say_repeats(void){}
static bool said_write(u32 a,u32 b){(void)a;(void)b;return false;}
#define lx_tell(...) ((void)0)
#define printf(...) ((void)0)
static u32 ioread32(void *p){
 unsigned offset=(unsigned)((unsigned char *)p-registers);assert(offset<sizeof(registers));accesses++;
 if(offset==ATH11K_PCI_WINDOW_REG_ADDRESS){posted=false;return selected|0x40000000;}
 assert(!posted);last_target=offset<0x80000 ? offset : ((selected&63)<<19)|(offset&0x7ffff);
 return last_target^0x5a5a5a5a;
}
static void iowrite32(u32 value,void *p){
 unsigned offset=(unsigned)((unsigned char *)p-registers);assert(offset<sizeof(registers));accesses++;
 if(offset==0x310c){assert(locked);selected=value&63;posted=true;return;}
 assert(!posted);last_target=offset<0x80000 ? offset : ((selected&63)<<19)|(offset&0x7ffff);last_value=value;
}
'''+state+'\nstatic spinlock_t pci_window_lock;\n'+''.join(function(bus,n) for n in ['window','refused','bus_read32','bus_write32'])
code=code.replace('__asm __volatile("dsb sy");','(void)0;')
code+=r'''
typedef uint64_t dma_addr_t;typedef unsigned gfp_t;struct device {};
static void lx_os_lock(void){assert(!locked);locked=1;}
static void lx_os_unlock(void){assert(locked);locked=0;}
static void *lx_os_radio_memory(unsigned size,unsigned long long *address){*address=0xa8000000;return calloc(1,size);}
'''+pool+mem[alloc_start:alloc_end]+r'''
int main(void){
 struct ath11k_base ab={.mem=registers};bus.renoir=true;bus.mission=true;bus.how=2;bus.said=600;
 const unsigned offsets[]={0x80000,0x1b80000,0xa00000,0x1e00000,0x1fffffc,0x1234};
 for(unsigned i=0;i<sizeof(offsets)/sizeof(*offsets);i++){
  u32 off=offsets[i];bus_write32(&ab,off,0xcafe0000+i);assert(last_target==off && last_value==0xcafe0000+i && !locked);
  assert(bus_read32(&ab,off)==(off^0x5a5a5a5a) && last_target==off && !locked);
 }
 unsigned before=accesses;offline=1;assert(!bus_read32(&ab,0x1b80000));bus_write32(&ab,0xa00000,1);assert(accesses==before);
 offline=0;bus_write32(&ab,3,1);assert(!bus_read32(&ab,0x2000000) && accesses==before);
 bus.renoir=false;assert(window(&ab,0x1234)==0x1234 && window(&ab,0xa00010)==0x80010 && window(&ab,0x1b80010)==0x100010);
 for(model=0;model<=1;model++){
  memset(&pool,0,sizeof(pool));assert(!lx_pool_init());assert(pool.free_count==(model ? 12288u : 8192u));
  dma_addr_t address=0;assert(linux_dma_alloc_coherent(NULL,4096,&address,0)==pool.memory);
  assert(linux_dma_alloc_coherent(NULL,0x4e0000,&address,0));
  assert(address==0xa8000000+(model ? 0x800000 : 4096));
  assert(linux_dma_alloc_coherent(NULL,0x398000,&address,0));
  if(model) assert(address==0xa9000000);
  unsigned old=pool.rings_used;assert(!linux_dma_alloc_coherent(NULL,POOL_RINGS,&address,0));assert(pool.rings_used==old);
  assert(!linux_dma_alloc_coherent(NULL,0,&address,0));assert(!linux_dma_alloc_coherent(NULL,SIZE_MAX,&address,0));
  free(pool.memory);assert(!locked);
 }
 puts("Renoir PCI bus: dynamic windows, posted-write ordering, offline guards, DMA alignment/capacity and redwood compatibility passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-pci-bus-') as tmp:
    p=Path(tmp);(p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-Wno-unused-parameter','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
