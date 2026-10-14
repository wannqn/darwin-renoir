#!/usr/bin/env python3
"""Run actual BHI code: DMA prerequisites, transfer failures and reset/rollback."""
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
src=(root/'xnu/files/bsd/dev/renoir_mhi_boot.h').read_text()
src=src.replace('__asm__ volatile("dsb sy" ::: "memory");','(void)0;')
src=src.replace('__asm__ volatile("dc civac, %0" : : "r"(line) : "memory");','(void)line;')
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include "renoir_mhi_protocol.h"
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
#define VM_WIMG_WCOMB 2
#define KERN_SUCCESS 0
#define KMA_KOBJECT 1
#define KMA_ZERO 2
#define KMA_DATA 4
#define VM_KERN_MEMORY_IOKIT 0
#define round_page(n) (((n)+16383)&~16383u)
#define kernel_map NULL
#define RADIO_ADDRESSES 0xa0000000ull
#define SMMU_SMR(n) (0x800+4*(n))
#define SMMU_S2CR(n) (0xc00+4*(n))
#define SMMU_CBAR(n) (4*(n))
#define SMMU_CBA2R(n) (0x800+4*(n))
#define SMMU_CB_FSR 0x58
#define SMMU_FSR_ALL 0xc00001fe
static uint32_t p[0x4000/4],g[0x2000/4],cb[0x1000/4],s[0x1000/4];
static uint32_t bar[0x10000/4],c[0x4000/4],d[0x4000/4],t[0x61000/4];
static uint8_t fw[0x100001], board_file[65536]="\177ELF",regdb_file[700],m3_file[266684];
static unsigned file_offsets[5],bdf_requests,resumes;
static bool sent_memory,sent_ready,want_resume,m3_pending;
static unsigned scenario,probe,allocs,frees,doorbells,bhie_doorbells,sleeps,reset_time,allocation;
static void *allocated;
static void *alias_copy;
static unsigned aliases;
static uint64_t completed_command;
static bool mapped;
static struct { vm_offset_t base; } apps_smmu,apps_smmu_context,apps_smmu_second;
static struct { unsigned match,context,old_smr,old_s2cr;bool on; } radio_space;
static void say(const char *s,...) { (void)s; }
static void sleep_us(unsigned n) { reset_time+=n; }
static void sleep_ms(unsigned n) { sleeps+=n;assert(sleeps<=20000); }
static uint32_t rd(vm_offset_t a) { return *(uint32_t *)a; }
static vm_offset_t ml_io_map_unmappable(vm_offset_t pa,vm_size_t size,unsigned flags) {
 unsigned ctrl=(sizeof(fw)+16383)&~16383u;
 assert(pa==0x98000000+ctrl && size==65536 && flags==VM_WIMG_WCOMB);
 if(scenario==20) return 0;
 aliases++;
 if(scenario==25) { alias_copy=malloc(65536);assert(alias_copy);memcpy(alias_copy,(uint8_t *)allocated+ctrl,65536);((uint8_t *)alias_copy)[0]^=1;return (uintptr_t)alias_copy; }
 return (uintptr_t)allocated+ctrl;
}
static void ml_io_unmap(vm_offset_t va,vm_size_t size) {
 assert(aliases && size==65536 && va==(alias_copy ? (uintptr_t)alias_copy : (uintptr_t)allocated+((sizeof(fw)+16383)&~16383u)));
 free(alias_copy);alias_copy=NULL;aliases--;
}
static void emit_event(unsigned type,unsigned value) {
 unsigned ctrl=(sizeof(fw)+16383)&~16383u;
 struct renoir_mhi_context *ev=(void *)((uint8_t *)allocated+ctrl+0x2000);
 uintptr_t offset=ev->rp-RADIO_ADDRESSES;
 uint32_t *entry=(void *)((uint8_t *)allocated+offset);
 if(type==0x21) { entry[0]=completed_command;entry[1]=completed_command>>32; }
 entry[2]=value<<24;entry[3]=type<<16;ev->rp+=16;
 if(scenario==21) ev->rp=UINT64_MAX;
 if(scenario==22) ev->wp=RADIO_ADDRESSES;
}
static void emit_transfer(unsigned channel,unsigned length,uint64_t completed,unsigned code) {
 unsigned ctrl=(sizeof(fw)+16383)&~16383u;
 struct renoir_mhi_context *ev=(void *)((uint8_t *)allocated+ctrl+0x2000+44);
 uint32_t *entry=(void *)((uint8_t *)allocated+(ev->rp-RADIO_ADDRESSES));
 entry[0]=completed;entry[1]=completed>>32;entry[2]=(code<<24)|length;entry[3]=(channel<<24)|(0x22<<16);ev->rp+=16;if(ev->rp==ev->base+ev->length)ev->rp=ev->base;
}
static void wr(vm_offset_t a,uint32_t v) {
 if(scenario==35 && a==(uintptr_t)&c[0x54/4]) return;
 if(scenario==3 && a==(uintptr_t)&p[(0x2000+4*0x15)/4] && v==0x01000100) return;
 if(scenario==5 && a==(uintptr_t)&c[1]) v&=~4u;
 *(uint32_t *)a=v;
 if(a==(uintptr_t)&bar[(0x100+0x18)/4]) {
  doorbells++;assert(mapped && radio_space.on);
  if(probe>=17) {
   assert(c[0x54/4]==RADIO_ADDRESSES+round_page(sizeof(fw))+0x9000);
   assert((c[0x50/4]&0x710000)==0x510000 && !c[0x58/4] && !c[0x5c/4] && !c[0x60/4]);
  }
  assert(p[(0x2000+4*0x15)/4]==0x01000100 && !(p[0x2c00/4]&1));
  assert((c[1]&6)==6 && (d[1]&6)==6);
  assert(bar[(0x100+8)/4]==RADIO_ADDRESSES && bar[(0x100+12)/4]==0);
  assert(bar[(0x100+0x10)/4]==0x80000 && v==1);
  if(scenario!=6) bar[(0x100+0x2c)/4]=scenario==7 ? 0xc0000000 : 0x80000000;
  if(scenario!=6 && scenario!=7 && scenario!=13) bar[(0x100+0x28)/4]=1;
  bar[0x48/4]=0x101;
 }
 if(a==(uintptr_t)&bar[0x38/4] && (v&0xff00)==0x200) {
  bar[0x48/4]=scenario==14 ? 0x101 : scenario==15 ? 4 : 0x200;
  if(scenario!=14 && scenario!=15) emit_event(0x20,2);
 }
 if(a==(uintptr_t)&bar[(0x400+20*8)/4]) {
  assert(probe>=19);
  unsigned ctrl=(sizeof(fw)+16383)&~16383u;
  unsigned slot=((v-RADIO_ADDRESSES-ctrl-0xa000)/16+31)%32;
  uint32_t *tre=(void *)((uint8_t *)allocated+ctrl+0xa000+slot*16);
  assert(tre[0]==RADIO_ADDRESSES+ctrl+0xe000 && !tre[1] && tre[3]==0x20200);
  uint32_t *outgoing=(void *)((uint8_t *)allocated+ctrl+0xe000);
  if(outgoing[1]==7) {
   assert(want_resume && tre[2]==52 && outgoing[2]==1 && outgoing[3]==0x4000 && outgoing[6]==7 && outgoing[7]==1);
   assert(outgoing[8]==7 && outgoing[9]==1 && outgoing[10]==0x4000);want_resume=false;resumes++;
   emit_transfer(20,52,RADIO_ADDRESSES+ctrl+0xa000+slot*16,2);return;
  }
  uint8_t *oq=(uint8_t *)outgoing+32;
  if(outgoing[1]==1 && oq[3]==0x25) {
   assert(probe>=25 && !want_resume);
   unsigned count=oq[35]|oq[36]<<8,kind=oq[37+count+7];assert(kind==1 || kind==4);
   uint32_t segment,remaining,board;memcpy(&segment,oq+28,4);memcpy(&remaining,oq+21,4);memcpy(&board,oq+14,4);
   const uint8_t *file=kind==1 ? board_file : regdb_file;
   unsigned size=kind==1 ? sizeof(board_file) : sizeof(regdb_file), offset=file_offsets[kind];
   assert(board==0xff && segment==offset/512 && remaining==size-offset && count==(remaining>512 ? 512 : remaining));
   assert(!memcmp(oq+37,file+offset,count) && oq[37+count+3]==(count==remaining));
   file_offsets[kind]+=count;bdf_requests++;
   uint32_t *packet=(void *)((uint8_t *)allocated+ctrl+0xc000);memset(packet,0,64);
   packet[0]=1;packet[1]=1;packet[2]=7;packet[3]=1;packet[5]=14;packet[6]=1;packet[7]=0x4000;
   if(bdf_requests%7==0) { packet[4]=1;want_resume=true; }
   uint8_t *q=(uint8_t *)packet+32;q[0]=2;q[1]=oq[1];q[2]=oq[2];q[3]=0x25;q[5]=7;q[7]=2;q[8]=4;
   unsigned next=(bar[(0x400+21*8)/4]-RADIO_ADDRESSES-ctrl-0xb000)/16;
   unsigned rxslot=(next+31)%32;
   emit_transfer(20,tre[2],RADIO_ADDRESSES+ctrl+0xa000+slot*16,2);
   emit_transfer(21,48,RADIO_ADDRESSES+ctrl+0xb000+rxslot*16,2);return;
  }
  if(outgoing[1]==1 && (oq[3]==0x47 || oq[3]==0x48 || oq[3]==0x22)) {
   assert(probe==26 && scenario>=45);unsigned msg=oq[3];
   if(msg==0x47) assert(tre[2]==40 && oq[5]==0);
   if(msg==0x48) assert(tre[2]==52 && oq[5]==11 && oq[7]==0x10 && oq[8]==8 && !oq[10]);
   if(msg==0x22) assert(tre[2]==52 && oq[5]==11 && oq[7]==1 && oq[8]==4 && oq[10]==7);
   emit_transfer(20,tre[2],RADIO_ADDRESSES+ctrl+0xa000+slot*16,2);
   if(scenario==48 && msg==0x22){bar[0x48/4]=4;return;}
   uint32_t *packet=(void *)((uint8_t *)allocated+ctrl+0xc000);memset(packet,0,64);
   packet[0]=1;packet[1]=1;packet[2]=7;packet[3]=1;packet[5]=14;packet[6]=1;packet[7]=0x4000;
   uint8_t *q=(uint8_t *)packet+32;q[0]=2;q[1]=oq[1];q[2]=oq[2];q[3]=msg;q[5]=7;q[7]=2;q[8]=4;
   q[10]=(scenario==45 && msg==0x47)||(scenario==46 && msg==0x48)||(scenario==47 && msg==0x22);
   unsigned next=(bar[(0x400+21*8)/4]-RADIO_ADDRESSES-ctrl-0xb000)/16;
   emit_transfer(21,48,RADIO_ADDRESSES+ctrl+0xb000+(next+31)%32*16,2);return;
  }
  if(outgoing[1]==1 && oq[3]==0x3c) {
   assert(probe==26 && !want_resume && file_offsets[1]==sizeof(board_file) && file_offsets[4]==sizeof(regdb_file));
   uint64_t address;uint32_t size;memcpy(&address,oq+10,8);memcpy(&size,oq+21,4);
   assert(address==0xa1400000 && size==sizeof(m3_file) && !memcmp((uint8_t *)allocated+address-RADIO_ADDRESSES,m3_file,size));
   uint32_t *packet=(void *)((uint8_t *)allocated+ctrl+0xc000);memset(packet,0,64);
   packet[0]=1;packet[1]=1;packet[2]=7;packet[3]=1;packet[5]=14;packet[6]=1;packet[7]=0x4000;
   uint8_t *q=(uint8_t *)packet+32;q[0]=2;q[1]=oq[1];q[2]=oq[2];q[3]=0x3c;q[5]=7;q[7]=2;q[8]=4;q[10]=scenario==43 ? 1 : 0;
   unsigned next=(bar[(0x400+21*8)/4]-RADIO_ADDRESSES-ctrl-0xb000)/16;
   emit_transfer(20,tre[2],RADIO_ADDRESSES+ctrl+0xa000+slot*16,2);
   emit_transfer(21,48,RADIO_ADDRESSES+ctrl+0xb000+(next+31)%32*16,2);
   m3_pending=scenario!=43 && scenario!=44;return;
  }
  assert(slot<=4);
  uint32_t *packet=(void *)((uint8_t *)allocated+ctrl+0xc000);
  memset(packet,0,64);
  packet[0]=1;packet[2]=7;packet[3]=0xfffffffe;packet[5]=20;packet[6]=1;packet[7]=0xfffffffe;
  if(slot==0) {
   assert(tre[2]==52);
   uint32_t *rx=(void *)((uint8_t *)allocated+ctrl+0xb000);
   assert(rx[0]==RADIO_ADDRESSES+ctrl+0xc000 && !rx[1] && rx[2]==8192 && rx[3]==0x20300);
   packet[1]=4;packet[8]=4;packet[9]=0x45;packet[10]=0x101;packet[11]=7;packet[12]=1;
   if(scenario!=33) {
    emit_transfer(20,52,RADIO_ADDRESSES+ctrl+0xa000+(scenario==29 ? 16 : 0),2);
    emit_transfer(21,scenario==30 ? 8193 : 52,RADIO_ADDRESSES+ctrl+0xb000+(scenario==31 ? 16 : 0),scenario==32 ? 3 : 2);
   }
  } else {
   assert(probe>=20 && tre[2]==(slot==4 ? 40u : slot==3 ? 80u : slot==2 ? 68u : probe==20 ? 40u : 64u));
   uint32_t *sent=(void *)((uint8_t *)allocated+ctrl+0xe000);
   unsigned message=slot==4 ? 0x24 : slot==3 ? 0x36 : slot==2 ? 0x34 : probe==20 ? 0x24 : 0x20;
   assert(sent[5]==(slot==4 ? 7u : slot==3 ? 45u : slot==2 ? 34u : probe==20 ? 7u : 30u) && sent[6]==7 && sent[7]==1 && sent[8]==((message<<24)|(slot<<8)));
   packet[1]=1;packet[3]=1;packet[5]=14;packet[7]=0x4000;
   uint8_t *q=(uint8_t *)packet+32;
   q[0]=2;q[1]=scenario==38 ? 9 : slot;q[3]=message;q[5]=scenario==37 ? 8 : 7;q[7]=2;q[8]=scenario==39 ? 255 : 4;q[10]=scenario==40 ? 1 : 0;
   emit_transfer(20,tre[2],RADIO_ADDRESSES+ctrl+0xa000+slot*16,2);
   emit_transfer(21,48,RADIO_ADDRESSES+ctrl+0xb000+(slot==4 ? 6 : slot==3 ? 4 : slot)*16,2);
  }
 }
 if(probe>=23 && a==(uintptr_t)&bar[(0x400+21*8)/4]) {
  unsigned ctrl=(sizeof(fw)+16383)&~16383u;
  uint32_t *packet=(void *)((uint8_t *)allocated+ctrl+0xc000);
  if(v==RADIO_ADDRESSES+ctrl+0xb040 && !sent_memory) {
   sent_memory=true;
   memset(packet,0,64);packet[0]=1;packet[1]=1;packet[2]=7;packet[3]=1;packet[5]=29;packet[7]=0x4000;
   uint8_t *q=(uint8_t *)packet+32;
   q[0]=4;q[3]=0x35;q[5]=22;q[7]=1;q[8]=19;q[10]=2;
   q[13]=0x4e;q[15]=1;q[21]=0x80;q[22]=0x39;q[24]=4;
   emit_transfer(21,64,RADIO_ADDRESSES+ctrl+0xb030,2);
  }
  if(v==RADIO_ADDRESSES+ctrl+0xb060 && !sent_ready) {
   sent_ready=true;
   memset(packet,0,64);packet[0]=1;packet[1]=1;packet[2]=7;packet[3]=1;packet[5]=7;packet[7]=0x4000;
   uint8_t *q=(uint8_t *)packet+32;q[0]=4;q[3]=0x37;
   emit_transfer(21,40,RADIO_ADDRESSES+ctrl+0xb050,2);
  }
 }
 if(m3_pending && a==(uintptr_t)&bar[(0x400+21*8)/4]) {
  m3_pending=false;unsigned ctrl=(sizeof(fw)+16383)&~16383u;
  uint32_t *packet=(void *)((uint8_t *)allocated+ctrl+0xc000);memset(packet,0,64);
  packet[0]=1;packet[1]=1;packet[2]=7;packet[3]=1;packet[5]=7;packet[6]=1;packet[7]=0x4000;
  uint8_t *q=(uint8_t *)packet+32;q[0]=4;q[3]=0x38;
  unsigned next=(v-RADIO_ADDRESSES-ctrl-0xb000)/16;
  emit_transfer(21,40,RADIO_ADDRESSES+ctrl+0xb000+(next+31)%32*16,2);
 }
 if(a==(uintptr_t)&bar[0x70/4]) {
  assert(probe>=18);
  unsigned ctrl=(sizeof(fw)+16383)&~16383u;
  completed_command=v-16+(scenario==27 ? 16 : 0);
  unsigned slot=(v-RADIO_ADDRESSES-ctrl-0x4000)/16-1;
  assert(slot<2);
  struct renoir_mhi_context *ctxt=(void *)((uint8_t *)allocated+ctrl+(20+slot)*44);
  assert(ctxt->config==0x201 && ctxt->type==1+slot && ctxt->event==1);
  assert(ctxt->base==RADIO_ADDRESSES+ctrl+0xa000+slot*0x1000 && ctxt->length==512);
  uint32_t *tre=(void *)((uint8_t *)allocated+ctrl+0x4000+slot*16);
  assert(tre[0]==0 && tre[1]==0 && tre[2]==0 && tre[3]==((20+slot)<<24|18<<16));
  if(scenario!=26) emit_event(0x21,scenario==28 ? 2 : 1);
 }
 if(a==(uintptr_t)&bar[(0x224+0x3c)/4]) {
  bhie_doorbells++;assert(probe>=17 && mapped && radio_space.on && v==2);
  unsigned ctrl=(sizeof(fw)+16383)&~16383u;
  assert(bar[0x58/4]==RADIO_ADDRESSES+ctrl && bar[0x60/4]==RADIO_ADDRESSES+ctrl+0x2000);
  assert(bar[0x68/4]==RADIO_ADDRESSES+ctrl+0x3000 && bar[0x88/4]==RADIO_ADDRESSES+allocation-1);
  assert(bar[(0x224+0x2c)/4]==RADIO_ADDRESSES+ctrl+0x8000 && bar[(0x224+0x34)/4]==3*16);
  struct renoir_mhi_vector *vec=(void *)((uint8_t *)allocated+ctrl+0x8000);
  assert(vec[0].address==RADIO_ADDRESSES && vec[0].size==0x80000);
  assert(vec[2].address==RADIO_ADDRESSES+0x100000 && vec[2].size==1);
  if(scenario!=16) bar[(0x224+0x44)/4]=scenario==17 ? 0xc0000000 : 0x80000000;
  /* Real firmware can leave BHI_EXECENV at SBL and report AMSS by event. */
  if(scenario!=16 && scenario!=17 && scenario!=18) emit_event(0x40,scenario==19 ? 3 : 2);
 }
}
static const uint8_t *image_file_in(const char *dir,const char *name,uint64_t *size) {
 assert(!strcmp(dir,"fw-wifi-renoir"));
 if(!strcmp(name,"bd_k9gl.elf")) { *size=sizeof(board_file);return board_file; }
 if(!strcmp(name,"regdb.bin")) { *size=sizeof(regdb_file);return regdb_file; }
 if(!strcmp(name,"m3.bin")) { *size=scenario==42 ? 0x100001 : sizeof(m3_file);return scenario==41 ? NULL : m3_file; }
 assert(!strcmp(name,"amss20.bin"));
 *size=scenario==8 ? 128 : scenario==11 ? 0x900000 : sizeof(fw);
 return scenario==1 ? NULL : fw;
}
static int kmem_alloc_contig(void *map,vm_offset_t *out,unsigned size,unsigned a,unsigned b,unsigned c,unsigned flags,unsigned tag) {
 (void)map;(void)a;(void)b;(void)c;(void)flags;(void)tag;
 assert(size==(probe>=17 ? round_page(sizeof(fw))+65536+(probe>=23 ? 0x2000000 : 0) : 0x80000));if(scenario==2) return 1;
 void *ptr=NULL;assert(!posix_memalign(&ptr,4096,size));memset(ptr,0,size);
 allocated=ptr;allocation=size;*out=(uintptr_t)ptr;allocs++;return 0;
}
static uint64_t kvtophys(vm_offset_t a) {
 assert(a);
 if(alias_copy && a==(uintptr_t)alias_copy) return 0x98000000+((sizeof(fw)+16383)&~16383u);
 assert(a>=(uintptr_t)allocated && a<(uintptr_t)allocated+allocation);
 uint64_t offset=a-(uintptr_t)allocated;
 return 0x98000000+offset+(scenario==24 ? 1 : scenario==23 && offset ? 16384 : 0);
}
static void kmem_free(void *map,vm_offset_t a,unsigned size) {
 (void)map;assert(size==allocation && !radio_space.on && !(c[1]&4));
 assert(t[(94*0x1000+4)/4]==0);
 if(mapped) assert(!memcmp((void *)a,fw,probe>=17 ? sizeof(fw) : 0x80000));
 frees++;free((void *)a);
}
static bool radio_space_find(void) {
 radio_space.match=3;radio_space.context=3;radio_space.old_smr=g[SMMU_SMR(3)/4];radio_space.old_s2cr=g[SMMU_S2CR(3)/4];
 return true;
}
static bool radio_enter(uint64_t a,uint64_t p,uint64_t n) {
 assert(a==RADIO_ADDRESSES && p==0x98000000 && n==allocation);mapped=true;return true;
}
static bool radio_space_on_for(uint32_t sid,uint32_t mask) {
 assert(sid==0x2401 && mask==0 && mapped);
 cb[0]=1;cb[0x20/4]=0x999;s[12/4]=0x10000;s[0x80c/4]=1;
 if(scenario==4) return false;
 g[SMMU_SMR(3)/4]=0x80002401;g[SMMU_S2CR(3)/4]=3;radio_space.on=true;return true;
}
static void radio_space_off(void) { radio_space.on=false; }
static void radio_space_faults(void) {}
''' + r'''
static void (*renoir_qrtr_input)(const uint8_t *,uint32_t);
static bool renoir_mhi_runtime(vm_offset_t bar) { (void)bar;return false; }
''' + src + r'''
int main(void) {
 apps_smmu.base=(uintptr_t)g;apps_smmu_context.base=(uintptr_t)cb;apps_smmu_second.base=(uintptr_t)s;
 unsigned crc=0;for(unsigned byte=0;byte<2;byte++) { crc^=byte ? 0 : 1;for(unsigned bit=0;bit<8;bit++) crc=((crc<<1)^((crc&128)?7:0))&255; }
 assert(crc==0x15);
 for(probe=16;probe<=26;probe++) for(scenario=0;scenario<(probe==26 ? 50u : probe>=20 ? 41u : probe==19 ? 37u : probe==18 ? 29u : probe>=17 ? 26u : 13u);scenario++) {
  memset(p,0,sizeof(p));memset(g,0,sizeof(g));memset(cb,0,sizeof(cb));memset(s,0,sizeof(s));
  memset(c,0,sizeof(c));memset(d,0,sizeof(d));memset(bar,0,sizeof(bar));memset(t,0,sizeof(t));
  memset(&radio_space,0,sizeof(radio_space));memset(fw,0x55,sizeof(fw));memcpy(fw,scenario==12 ? "bad!" : "\177ELF",4);
  memset(file_offsets,0,sizeof(file_offsets));bdf_requests=resumes=0;sent_memory=sent_ready=want_resume=m3_pending=false;
  allocs=frees=doorbells=bhie_doorbells=sleeps=reset_time=allocation=aliases=0;mapped=false;c[1]=2;c[0x50/4]=scenario==34 ? 0 : scenario==36 ? 0x01047005 : 0x010a7005;d[1]=2;t[(94*0x1000+4)/4]=2;
  bar[0x28/4]=scenario==9 ? 0xfffffff0 : 0x100;bar[(0x100+0x28)/4]=scenario==10 ? 1 : 0;
  bar[0x18/4]=0x400;bar[0x20/4]=0x800;bar[0x2c/4]=0x224;
  p[0x2c00/4]=1;for(unsigned i=0;i<256;i++) p[(0x2000+4*i)/4]=i+10;
  cb[0x20/4]=0x123;s[12/4]=0x456;s[0x80c/4]=0x789;g[SMMU_SMR(3)/4]=0x80;g[SMMU_S2CR(3)/4]=0x20003;
  uint32_t saved_p[sizeof(p)/4],saved_cb[sizeof(cb)/4],saved_s[sizeof(s)/4],saved_g[sizeof(g)/4];
  memcpy(saved_p,p,sizeof(p));memcpy(saved_cb,cb,sizeof(cb));memcpy(saved_s,s,sizeof(s));memcpy(saved_g,g,sizeof(g));
  renoir_bhi_host((uintptr_t)p,(uintptr_t)t);
  bool ok=renoir_bhi_load((uintptr_t)bar,(uintptr_t)c,(uintptr_t)d,probe==26 && scenario>=45 ? 28 : probe);
  if(ok!=(scenario==0 || scenario==49)) fprintf(stderr,"probe=%u scenario=%u memory_count=%u ready=%u reply=%u tx=%u message=%x\n",probe,scenario,renoir_bhi.memory_count,renoir_bhi.memory_ready,renoir_bhi.reply_seen,renoir_bhi.tx_done,renoir_bhi.qmi_message);
  assert(ok==(scenario==0 || scenario==49));
  if(probe>=25 && scenario==0) { assert(file_offsets[1]==sizeof(board_file) && file_offsets[4]==sizeof(regdb_file) && resumes>0 && !want_resume); }assert(!(c[1]&4) && d[1]==2);
  assert(c[0x50/4]==(scenario==34 ? 0u : scenario==36 ? 0x01047005u : 0x010a7005u) && !c[0x54/4] && !c[0x58/4] && !c[0x5c/4] && !c[0x60/4]);
  assert(doorbells==((scenario==0 || scenario==6 || scenario==7 || (scenario>=13 && scenario<=22) || (scenario>=25 && scenario<=33) || scenario>=37) ? 1u : 0u));
  assert(bhie_doorbells==((probe>=17 && (scenario==0 || (scenario>=16 && scenario<=19) || (scenario>=26 && scenario<=33) || scenario>=37)) ? 1u : 0u));
  if(scenario==0) { renoir_mhi_quiesce();assert(!frees && reset_time>=1000); }
  else t[(94*0x1000+4)/4]=0;
  renoir_bhi_cleanup(true);
  assert(allocs==frees && !aliases && !renoir_bhi.buffer && !renoir_bhi.active);
  assert(!memcmp(saved_p,p,sizeof(p)) && !memcmp(saved_cb,cb,sizeof(cb)) && !memcmp(saved_s,s,sizeof(s)) && !memcmp(saved_g,g,sizeof(g)));
 }
 uint32_t packet[64]={1,1,7,1,0,14,1,0x4000};
 uint8_t *q=(uint8_t *)packet+32;
 q[0]=2;q[1]=1;q[3]=0x24;q[5]=7;q[7]=2;q[8]=4;
 renoir_bhi.wlfw_node=7;renoir_bhi.wlfw_port=1;renoir_bhi.qmi_message=0x24;renoir_bhi.qmi_transaction=1;
 for(unsigned n=0;n<46;n++) { renoir_bhi.reply_seen=false;renoir_mhi_inspect_qrtr((uintptr_t)packet,n);assert(!renoir_bhi.reply_seen); }
 renoir_mhi_inspect_qrtr((uintptr_t)packet,46);assert(renoir_bhi.reply_seen && renoir_bhi.reply_ok);
 renoir_bhi.reply_seen=false;q[8]=255;q[9]=255;renoir_mhi_inspect_qrtr((uintptr_t)packet,46);assert(!renoir_bhi.reply_seen);
 q[8]=4;q[9]=0;q[10]=1;renoir_mhi_inspect_qrtr((uintptr_t)packet,46);assert(renoir_bhi.reply_seen && !renoir_bhi.reply_ok);
 renoir_bhi.reply_seen=false;q[10]=0;q[1]=2;renoir_mhi_inspect_qrtr((uintptr_t)packet,46);assert(!renoir_bhi.reply_seen);
 q[1]=1;packet[5]=15;q[5]=8;renoir_mhi_inspect_qrtr((uintptr_t)packet,47);assert(!renoir_bhi.reply_seen);
 memset(packet,0,sizeof(packet));packet[0]=1;packet[1]=1;packet[2]=7;packet[3]=1;packet[5]=20;packet[7]=0x4000;
 q=(uint8_t *)packet+32;q[0]=4;q[3]=0x35;q[5]=13;q[7]=1;q[8]=10;q[10]=1;q[13]=0x20;q[15]=1;
 for(unsigned n=0;n<52;n++) { renoir_bhi.memory_count=0;renoir_mhi_inspect_qrtr((uintptr_t)packet,n);assert(!renoir_bhi.memory_count); }
 renoir_mhi_inspect_qrtr((uintptr_t)packet,52);assert(renoir_bhi.memory_count==1 && renoir_bhi.memory_sizes[0]==0x200000 && renoir_bhi.memory_types[0]==1);
 renoir_bhi.memory_count=0;q[10]=53;renoir_mhi_inspect_qrtr((uintptr_t)packet,52);assert(!renoir_bhi.memory_count);
 q[10]=1;q[19]=3;renoir_mhi_inspect_qrtr((uintptr_t)packet,52);assert(!renoir_bhi.memory_count);
 q[19]=2;packet[5]=46;q[5]=39;q[8]=36;renoir_mhi_inspect_qrtr((uintptr_t)packet,78);assert(renoir_bhi.memory_count==1);
 puts("Renoir BHI/BHIE: firmware validation, DMA ordering, M0/mission transitions, transfer failures, panic reset and full rollback passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-bhi-') as tmp:
    p=Path(tmp);(p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-I',str(root/'xnu/files/bsd/dev'),'-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
