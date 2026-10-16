#!/usr/bin/env python3
"""Exercise the real TFA container parser, including CRC, bounds and profile isolation."""
from pathlib import Path
import tempfile, subprocess
r=Path(__file__).resolve().parents[1]
code=r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "renoir_tfa_container.h"
static uint8_t d[192],good[192];
static void w16(unsigned a,unsigned v){d[a]=v;d[a+1]=v>>8;}
static void w32(unsigned a,unsigned v){w16(a,v);w16(a+2,v>>16);}
static void crc(void){uint32_t c=~0u;for(unsigned i=14;i<sizeof(d);i++){
 c^=d[i];for(unsigned j=0;j<8;j++)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}w32(10,~c);}
static bool openplan(unsigned dev){struct renoir_tfa_container c;struct renoir_tfa_plan p;
 return renoir_tfa_open(&c,d,sizeof(d))&&renoir_tfa_stereo(&c,dev,&p);}
int main(void){
 memcpy(d,"PM3_01",6);w32(6,sizeof(d));w16(40,2);w16(42,1);
 w32(46,54);w32(50,82);
 for(unsigned i=0;i<2;i++){unsigned a=i?82:54;d[a]=2;d[a+2]=0x34+i;
  w32(a+8,0x03000000u+(i?134:130));w32(a+12,0x10000000u+150);w32(a+16,0x01000000u+110);}
 memcpy(d+130,"RCV",4);memcpy(d+134,"SPK",4);memcpy(d+138,"stereo",7);
 d[110]=3;w16(112,0x1234);w32(114,0x03000000u+138);
 w32(118,0x10000000u+158);w32(122,0x11000000u);
 w16(150,9);w16(152,0x0203);w16(158,1);w16(160,0x0040);crc();memcpy(good,d,sizeof(d));
 assert(openplan(0)&&openplan(1)&&!openplan(2));
 struct renoir_tfa_container c;struct renoir_tfa_plan p;
 assert(renoir_tfa_open(&c,d,sizeof(d))&&renoir_tfa_stereo(&c,0,&p));
 assert(p.address==0x34&&p.count==2&&p.fields[0].field==0x0203&&p.fields[0].value==9);
 for(unsigned n=0;n<sizeof(d);n++)assert(!renoir_tfa_open(&c,d,n));
 d[150]^=1;assert(!openplan(0));memcpy(d,good,sizeof(d));
 w32(46,0xfffffe);crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 d[56]=0x35;crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 w16(152,0x02ff);crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 w16(150,16);crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 memcpy(d+138,"calibr",7);crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 w32(118,0x04000000u+158);crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 d[110]=255;crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 w16(112,0);crc();assert(!openplan(0));memcpy(d,good,sizeof(d));
 for(unsigned i=0;i<1000;i++){memcpy(d,good,sizeof(d));unsigned at=14+rand()%(sizeof(d)-14);
  d[at]^=(uint8_t)(1+rand()%255);crc();(void)openplan(0);(void)openplan(1);}
 puts("TFA9873 container: CRC, two distinct chips, exact stereo profile, field/range bounds and malformed metadata passed");
 return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-tfa-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Wall','-Werror','-fsanitize=address,undefined','-I'+str(r/'xnu/files/bsd/dev'),str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
