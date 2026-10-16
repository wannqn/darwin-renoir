#!/usr/bin/env python3
"""Run actual Renoir AFE route/rollback code with a fault-injected APR transport."""
from pathlib import Path
import tempfile,subprocess,re
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/redwood_sound.c').read_text()
def function(name):
 a=s.index(name+'(');a=s.rfind('static ',0,a);b=s.index('{',a);depth=1;i=b+1
 while depth:
  depth+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]
def define(name):return re.search(r'^#define '+name+r' +.*$',s,re.M)[0]
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
#include <string.h>
static bool sound_renoir=true,off=true,clock_on,group_on,port_on,feedback_on;
static unsigned calls,fail_at,ops[16];
#define RATE 48000
#define SLOT_BITS 32
#define SLOTS 2
#define CLOCK_PRI_TDM_IBIT 0x200
#define CLOCK_INVERT_COUPLE_NO 4
#define AFE_MODULE_CLOCK_SET 0x1028f
#define AFE_PARAM_ID_CLOCK_SET 0x10290
#define AFE_MODULE_GROUP_DEVICE 0x10254
#define AFE_PARAM_ID_GROUP_DEVICE_ENABLE 0x10256
#define APR_SVC_AFE 4
#define AFE_PORT_CMD_SET_PARAM_V2 0x100ef
#define AFE_PORT_CMD_DEVICE_START 0x100e5
#define AFE_PORT_CMD_DEVICE_STOP 0x100e6
#define GROUP 0x9100
#define say(...) ((void)0)
static bool renoir_tfa_is_off(void){return off;}
struct afe_clock_set {uint32_t version,id,hz;uint16_t attribute,root;uint32_t enable;} __attribute__((packed));
struct afe_group_enable {uint16_t group,enable;} __attribute__((packed));
static bool command(const char *what,uint8_t service,uint16_t port,uint32_t opcode,const void *buf,uint32_t size,uint32_t wanted,void *answer){
 (void)what;assert(service==4 && !port && !wanted && !answer && calls<16);
 if(opcode==0x100ef){
  assert(size==48);uint32_t w[12];memcpy(w,buf,size);
  assert((w[0]&0xffff)==0x1004 || (w[0]&0xffff)==0x1005);
  assert((w[0]>>16)==32 && w[4]==0x1020c && w[5]==0x1020d && w[6]==20 && w[7]==1);
  assert((w[8]&0xffff)==24 && (w[8]>>16)==((w[0]&0xffff)==0x1004?2:1));
  assert(w[9]==0x10001 && w[10]==96000 && !w[11]);
 }else{assert(size==4 && (opcode==0x100e5 || opcode==0x100e6));}
 ops[calls++]=opcode;return calls!=fail_at;
}
static bool afe_service_param(const char *what,uint32_t module,uint32_t param,const void *buf,uint16_t size){
 (void)what;assert(module==0x1028f && param==0x10290 && size==20);
 const struct afe_clock_set *c=buf;
 assert(c->version==1 && c->id==0x104 && c->hz==6144000 && c->attribute==1 && !c->root);
 assert(c->enable==(calls==0));ops[calls++]=c->enable?1:0;return calls!=fail_at;
}
"""+'\n'+define('PORT')+'\n'+define('AUDIO_STREAM')+'\n'+function('afe_clock')+'\n'+function('afe_renoir_on')+'\n'+function('afe_off')+r"""
int main(void){
 assert(PORT==0x1004 && AUDIO_STREAM==0x2001);sound_renoir=false;
 assert(PORT==0x9000 && AUDIO_STREAM==0x1801);sound_renoir=true;
 off=false;assert(!afe_renoir_on() && calls==0);off=true;
 for(unsigned fail=0;fail<=8;fail++){
  calls=0;fail_at=fail;
  bool ok=afe_renoir_on();assert(ok==(fail==0 || fail>5));
  afe_off();assert(!clock_on && !port_on && !feedback_on && !group_on);
  assert(ops[calls-1]==0);
  if(fail==1)assert(calls==2);
  else if(fail==2)assert(calls==3);
  else if(fail==3)assert(calls==5);
  else if(fail==4)assert(calls==6);
  else assert(calls==8);
 }
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-sound-route-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Renoir sound route: AFE ABI, SD0/SD1, clock, board stream/port selection and cleanup at every command failure passed')
