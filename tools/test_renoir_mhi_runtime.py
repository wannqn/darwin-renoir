#!/usr/bin/env python3
"""Check actual MHI runtime queue ownership, bounds and TX backpressure."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[1]
src=(root/'xnu/files/bsd/dev/renoir_mhi_runtime.h').read_text()
src=src[:src.index("/* CNSS2's 0x420000")]
a=src.index('static void\nrenoir_link_input');b=src.index('static void\nrenoir_link_flush',a)
src=src[:a]+src[b:]
code=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
typedef uintptr_t vm_offset_t;
#define LCK_MTX_DECLARE(name,group) int name
#define Z_WAITOK 0
struct glink_packet {struct glink_packet *next;uint32_t length;uint8_t data[];};
static unsigned owned,locked,fail_alloc,submitted,submitted_length;
static unsigned char control[65536];
static struct {bool tx_done;vm_offset_t control_alias;} renoir_bhi;
static void *kalloc_data(size_t n,int flags){(void)flags;assert(!locked);if(fail_alloc)return NULL;owned++;return malloc(n);}
static void kfree_data(void *p,size_t n){(void)n;assert(owned);owned--;free(p);}
static void lck_mtx_lock(int *l){(void)l;assert(!locked);locked=1;}
static void lck_mtx_unlock(int *l){(void)l;assert(locked);locked=0;}
static void wr(vm_offset_t a,uint32_t v){assert(a>=(uintptr_t)control+0xe000 && a<=(uintptr_t)control+65532);memcpy((void *)a,&v,4);}
static void renoir_mhi_submit_tx(vm_offset_t bar,unsigned n){(void)bar;submitted++;submitted_length=n;renoir_bhi.tx_done=false;}
'''+src+r'''
int main(void){
 renoir_bhi.control_alias=(uintptr_t)control;renoir_link.wanted=true;
 uint8_t packet[8192];for(unsigned i=0;i<sizeof(packet);i++)packet[i]=i;
 assert(renoir_link_send(NULL,1)==EMSGSIZE && renoir_link_send(packet,0)==EMSGSIZE && renoir_link_send(packet,8193)==EMSGSIZE && !owned);
 fail_alloc=1;assert(renoir_link_send(packet,3)==ENOMEM && !owned);fail_alloc=0;
 for(unsigned i=0;i<64;i++)assert(!renoir_link_send(packet,i+1));
 assert(renoir_link_send(packet,1)==ENETDOWN && owned==64 && renoir_link.queued==64);
 renoir_bhi.tx_done=false;renoir_link_flush();assert(!submitted && owned==64);
 for(unsigned i=0;i<64;i++){
  memset(control,0x5a,sizeof(control));renoir_bhi.tx_done=true;renoir_link_flush();
  assert(submitted_length==i+1 && !memcmp(control+0xe000,packet,i+1));
  for(unsigned j=0;j<0xe000;j++)assert(control[j]==0x5a);
  for(unsigned j=i+1;j<((i+4)&~3u);j++)assert(!control[0xe000+j]);
 }
 assert(!owned && !renoir_link.first && !renoir_link.last && !renoir_link.queued);
 assert(!renoir_link_send(packet,8192));renoir_bhi.tx_done=true;renoir_link_flush();assert(submitted_length==8192 && !memcmp(control+0xe000,packet,8192));
 renoir_link.wanted=false;assert(renoir_link_send(packet,3)==ENETDOWN && !owned);
 unsigned old=submitted;renoir_bhi.tx_done=true;renoir_link_flush();assert(submitted==old && !locked);
 puts("Renoir MHI runtime: bounded queue, allocation/stop failures, single-buffer ownership, FIFO, backpressure and padding passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-mhi-runtime-') as tmp:
    p=Path(tmp);(p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
