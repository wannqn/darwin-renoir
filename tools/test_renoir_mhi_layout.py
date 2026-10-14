#!/usr/bin/env python3
"""Check real MHI context ABI and BHIE segmentation at arena boundaries."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "renoir_mhi_protocol.h"
int main(void) {
 uint8_t dump[256]={0};uint32_t reason_size=123,header=136;uint64_t file_size=4;
 memcpy(dump+4,&header,4);memcpy(dump+8+16,&file_size,8);memcpy(dump+72+16,&file_size,8);
 memcpy(dump+72+44,"Q6-SFR.bin",11);memcpy(dump+140,"fail",4);
 assert(renoir_rddm_sfr(dump,sizeof(dump),&reason_size)==dump+140 && reason_size==4);
 assert(!renoir_rddm_sfr(NULL,sizeof(dump),&reason_size) && !reason_size);
 assert(!renoir_rddm_sfr(dump,7,&reason_size));
 assert(!renoir_rddm_sfr(dump,135,&reason_size));
 file_size=UINT64_MAX;memcpy(dump+8+16,&file_size,8);assert(!renoir_rddm_sfr(dump,sizeof(dump),&reason_size));
 header=137;memcpy(dump+4,&header,4);assert(!renoir_rddm_sfr(dump,sizeof(dump),&reason_size));
 header=8+7*64;memcpy(dump+4,&header,4);assert(!renoir_rddm_sfr(dump,sizeof(dump),&reason_size));
 const uint32_t sizes[]={0x80000,0x80001,5197824,0x800000};
 for(unsigned test=0;test<4;test++) {
  uint32_t size=sizes[test],control=(size+16383)&~16383u,allocation=control+65536;
  uint8_t *arena=malloc(allocation+16);assert(arena);memset(arena,0x5a,allocation+16);
  struct renoir_mhi_layout layout;
  assert(renoir_mhi_make_layout(arena,size,allocation,0xa0000000,&layout));
  for(unsigned i=0;i<size;i++) assert(arena[i]==0x5a); /* firmware never overwritten */
  for(unsigned i=allocation;i<allocation+16;i++) assert(arena[i]==0x5a);
  struct renoir_mhi_context *ch=(void *)(arena+control),*er=(void *)(arena+control+0x2000),*cmd=(void *)(arena+control+0x3000);
  assert(sizeof(*ch)==44 && offsetof(struct renoir_mhi_context,base)==12);
  for(unsigned i=0;i<128;i++) assert(ch[i].config==0); /* all channels disabled */
  assert(ch[20].type==1 && ch[21].type==2 && ch[20].event==1 && ch[21].event==1);
  for(unsigned i=0;i<2;i++) {
   assert(er[i].type==1 && er[i].event==0 && er[i].rp==er[i].base);
   assert(er[i].wp==er[i].base+er[i].length-16);
   assert(er[i].base>=0xa0000000+control && er[i].base+er[i].length<=0xa0000000+allocation);
   assert(!(er[i].base&(er[i].length-1))); /* ring size alignment */
  }
  assert(cmd->rp==cmd->base && cmd->wp==cmd->base && cmd->length==2048);
  struct renoir_mhi_vector *vec=(void *)(arena+layout.vectors);
  uint64_t offset=0;
  for(unsigned i=0;i<layout.vector_size/16;i++) {
   assert(vec[i].address==0xa0000000+offset && vec[i].size>0 && vec[i].size<=0x80000);
   offset+=vec[i].size;assert(offset<=size);
  }
  assert(offset==size && layout.vector_size==((size+0x7ffff)/0x80000)*16);
  assert(!renoir_mhi_make_layout(arena,size,allocation-1,0xa0000000,&layout));
  assert(!renoir_mhi_make_layout(arena,size,allocation,UINT64_MAX-4095,&layout));
  free(arena);
 }
 uint8_t tiny[32];struct renoir_mhi_layout layout;
 assert(!renoir_mhi_make_layout(tiny,0,32,0,&layout));
 assert(!renoir_mhi_make_layout(tiny,0x800001,32,0,&layout));
 assert(!renoir_mhi_make_layout(tiny+1,0x80000,0x90000,0,&layout));
 uint8_t reply[900];uint32_t used=0,mem_sizes[]={0x4e0000,0x398000},types[]={1,4};
 assert(renoir_mhi_memory_reply(reply,sizeof(reply),mem_sizes,types,2,0xa0508000,0x1000000,&used)==38);
 assert(used==0xe90000 && reply[0]==1 && reply[1]==35 && reply[2]==0 && reply[3]==2);
 uint64_t addr;memcpy(&addr,reply+4,8);assert(addr==0xa0800000);
 memcpy(&addr,reply+21,8);assert(addr==0xa1000000);assert(reply[20]==0 && reply[37]==0);
 memset(reply,0x5a,sizeof(reply));
 assert(!renoir_mhi_memory_reply(reply,37,mem_sizes,types,2,0xa0508000,0x1000000,&used));
 assert(!renoir_mhi_memory_reply(reply,sizeof(reply),mem_sizes,types,2,0xa0508000,0xe8ffff,&used));
 assert(!renoir_mhi_memory_reply(reply,sizeof(reply),mem_sizes,types,2,UINT64_MAX-16383,0x1000000,&used));
 mem_sizes[0]=0;assert(!renoir_mhi_memory_reply(reply,sizeof(reply),mem_sizes,types,2,0xa0508000,0x1000000,&used));
 for(unsigned i=0;i<sizeof(reply);i++) assert(reply[i]==0x5a);
 uint8_t data[768],bdf[1100];memset(data,0x6b,sizeof(data));
 assert(renoir_mhi_bdf_chunk(bdf,sizeof(bdf),data,512,700,0,0xff,1)==550);
 assert(bdf[0]==1 && bdf[3]==1 && bdf[4]==0x10 && bdf[7]==0xff);
 assert(bdf[25]==0x13 && bdf[26]==2 && bdf[27]==2 && bdf[28]==0 && bdf[29]==2);
 assert(!memcmp(bdf+30,data,512) && !bdf[545] && bdf[549]==1);
 assert(renoir_mhi_bdf_chunk(bdf,sizeof(bdf),data,188,188,1,0xff,4)==226);
 assert(bdf[221]==1 && bdf[225]==4);
 assert(!renoir_mhi_bdf_chunk(bdf,549,data,512,700,0,0xff,1));
 assert(!renoir_mhi_bdf_chunk(bdf,sizeof(bdf),data,512,511,0,0xff,1));
 puts("Renoir MHI layout: context ABI, ring alignment, vector bounds and firmware preservation passed");
}
'''
code=code.replace('#include <assert.h>','#include <assert.h>\n#include <stddef.h>')
with tempfile.TemporaryDirectory(prefix='renoir-mhi-layout-') as tmp:
    p=Path(tmp);(p/'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-I',str(root/'xnu/files/bsd/dev'),'-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
