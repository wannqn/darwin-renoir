#!/usr/bin/env python3
"""Execute actual Titan580 bus/PHY/TCS code with MMIO fault injection."""
from pathlib import Path
import subprocess
import tempfile
repo=Path(__file__).resolve().parents[1]
code=r'''#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include "renoir_camera_core.h"
struct mock {uint32_t reg[0x2200/4];unsigned writes,fail;bool timeout,bad_status;uint32_t timeout_reg;};
static bool put(void*p,uint32_t r,uint32_t v,bool check){
 struct mock*m=p;(void)check;assert(!(r&3)&&r<0x2200);
 if(++m->writes==m->fail)return false;
 m->reg[r/4]=v;return true;
}
static uint32_t get(void*p,uint32_t r){struct mock*m=p;assert(!(r&3)&&r<0x2200);return m->reg[r/4];}
static bool wait(void*p,uint32_t r,uint32_t mask,uint32_t want,uint32_t us){
 struct mock*m=p;(void)mask;(void)want;assert(us<=200000);
 if(r==4)m->reg[0x3c/4]=m->bad_status?0:0x10100;
 return !m->timeout && r!=m->timeout_reg;
}
static void delay(void*p,uint32_t us){(void)p;assert(us<=2000);}
int main(void){
 assert(rcam_dphy_rate_supported(2137600000ull));
 assert(!rcam_dphy_rate_supported(0) && !rcam_dphy_rate_supported(3200000000ull));
 struct mock m={0};struct rcam_io io={&m,put,wait,delay,get};
 assert(rcam_ife_start(&io,0x40001000,2400000,2400000,2000));
 assert(m.reg[0x1c00/4]==0x10001 && m.reg[0x1c04/4]==0x40001000);
 assert(m.reg[0x1a18/4]==16 && m.reg[0x20/4]==1);
 assert(m.reg[0x1c10/4]==0 && m.reg[0x1c14/4]==2000);
 unsigned n=m.writes;
 for(unsigned f=1;f<=n;f++){
  memset(&m,0,sizeof(m));m.fail=f;
  assert(!rcam_ife_start(&io,0x40001000,2400000,2400000,2000));
  assert(m.reg[0x1c00/4]==0 && m.reg[0x1a18/4]==0);
 }
 memset(&m,0,sizeof(m));m.timeout=true;
 assert(!rcam_ife_start(&io,0x40001000,2400000,2400000,2000));assert(m.reg[0x1c00/4]==0);
 memset(&m,0,sizeof(m));
 assert(!rcam_ife_start(&io,0x40001001,100,100,16));assert(m.writes==0);
 assert(!rcam_ife_start(&io,0xfffffff0,32,32,16));assert(m.writes==0);
 assert(!rcam_ife_start(&io,0x40000000,100,200,16));assert(m.writes==0);
 assert(!rcam_ife_start(&io,0x40001000,2400000,2400000,0));
 assert(!rcam_ife_start(&io,0x40001000,2400000,2400000,1999));
 assert(!rcam_ife_start(&io,0x40001000,2400001,2400001,2000));
 for(unsigned lanes=1;lanes<=4;lanes++){
  memset(&m,0,sizeof(m));assert(rcam_phy_start(&io,lanes,0x3210,14));
  assert(m.reg[0x814/4]==0xd5 && m.reg[0x81c/4]==0x5a);
  assert(m.reg[0x710/4]==0x52 && m.reg[8/4]==14 && m.reg[0x708/4]==14);
  assert(m.reg[0x700/4]==0x80 && m.reg[0x600/4]==0x91);
 }
 n=m.writes;
 for(unsigned f=1;f<=n;f++){
  memset(&m,0,sizeof(m));m.fail=f;
  assert(!rcam_phy_start(&io,4,0x3210,19));
  assert(m.reg[0x814/4]==0 && m.reg[0x818/4]==0);
 }
 memset(&m,0,sizeof(m));assert(!rcam_phy_start(&io,2,0x00,19));assert(m.writes==0);
 assert(!rcam_phy_start(&io,4,0x4210,19));assert(m.writes==0);
 assert(!rcam_phy_start(&io,4,0x3210,256));assert(m.writes==0);
 static const unsigned offsets[]={0,0x10,0x14,0x1c,0x30,0x34,0x38};
 for(unsigned f=0;f<21;f++){
  memset(&m,0,sizeof(m));uint32_t saved[7];
  for(unsigned i=0;i<7;i++){saved[i]=0x100+i;m.reg[offsets[i]/4]=saved[i];}
  m.reg[0x40/4]=3;m.fail=f;uint32_t value=0;
  bool ok=rcam_tcs_transfer(&io,0x30000,false,&value);
  if(!f){assert(ok&&value==3);}else assert(!ok);
  for(unsigned i=0;i<7;i++)assert(m.reg[offsets[i]/4]==saved[i]);
 }
 memset(&m,0,sizeof(m));m.reg[0x14/4]=1u<<24;
 uint32_t value=5;assert(rcam_tcs_transfer(&io,0x30000,true,&value));
 assert(!(m.reg[0x14/4]&(1u<<24)));
 memset(&m,0,sizeof(m));m.timeout=true;
 assert(!rcam_tcs_transfer(&io,0x30000,true,&value));assert(m.writes==0);
 memset(&m,0,sizeof(m));m.timeout_reg=4;m.reg[0x10/4]=0x55;
 assert(!rcam_tcs_transfer(&io,0x30000,true,&value));assert(m.reg[0x10/4]==0x55);
 memset(&m,0,sizeof(m));m.bad_status=true;
 assert(!rcam_tcs_transfer(&io,0x30000,true,&value));
 puts("Titan580: bus-v3 DMA setup/IRQ, D-PHY1.2.4, bounds, every setup-write failure, reset timeout and TCS preservation passed");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(repo/'xnu/files/bsd/dev'),str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
