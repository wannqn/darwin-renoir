#!/usr/bin/env python3
"""Run upstream full-resolution ISP on synthetic RAW10, with ASan/UBSan."""
from pathlib import Path
import subprocess
import tempfile
repo=Path(__file__).resolve().parents[1]
code=r'''#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "camera_isp.h"
int main(void){
 struct isp isp;isp_init(&isp);
 struct redwood_camera_frame f={.width=8,.height=6,.stride=16,.black=64};
 unsigned char raw[96],y[72],uv[36],by[72],buv[36];
 int previous=-1;
 for(int sample=64;sample<=1023;sample+=(sample==64 ? 448 : 511)){
  memset(raw,0,sizeof(raw));
  for(unsigned row=0;row<6;row++)for(unsigned group=0;group<2;group++){
   unsigned char *b=raw+16*row+5*group;
   for(int i=0;i<4;i++)b[i]=sample>>2;
   b[4]=(sample&3)*0x55;
  }
  for(unsigned bayer=0;bayer<4;bayer++)for(int range=0;range<2;range++){
   f.bayer=bayer;memset(y,0xa5,sizeof(y));memset(uv,0xa5,sizeof(uv));
   memset(by,0xa5,sizeof(by));memset(buv,0xa5,sizeof(buv));
   isp_render_full_nv12(&isp,&f,raw,y,12,uv,12,0,6,range);
   for(unsigned row=0;row<6;row+=2)isp_render_full_nv12(&isp,&f,raw,by,12,buv,12,row,row+2,range);
   assert(memcmp(y,by,sizeof(y))==0 && memcmp(uv,buv,sizeof(uv))==0);
   for(unsigned row=0;row<6;row++)for(unsigned x=0;x<12;x++){
    if(x<8)assert(y[row*12+x]==y[0]);else assert(y[row*12+x]==0xa5);
   }
   for(unsigned row=0;row<3;row++)for(unsigned x=0;x<12;x++){
    if(x<8)assert(uv[row*12+x]>=127 && uv[row*12+x]<=129);else assert(uv[row*12+x]==0xa5);
   }
   if(sample==64)assert(y[0]==(range?16:0));
   if(sample==1023)assert(y[0]==(range?235:255));
   if(!range && bayer==0){assert(y[0]>previous);previous=y[0];}
  }
 }
 puts("Camera ISP: RAW10 black/grey/white, four Bayer orders, full/video range, row bands and stride padding passed");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(repo/'userland/src'),'-I'+str(repo/'xnu/files/bsd/sys'),str(p/'test.c'),str(repo/'userland/src/camera_isp.c'),'-lm','-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
