#!/usr/bin/env python3
"""Encode the real Renoir HOST_CAP extension through the actual kernel QMI codec."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1]
s=(r/'wifi/lx/src/lx_bus.c').read_text()
a=s.index('struct renoir_ddr_range');b=s.index('int\nlx_qmi_send_request(',a)
s=s[a:b].replace('return qmi_send_request(', 'return capture_request(')
ath=r/'xnu-deps/build/ath11k/src/ath11k'
tables=subprocess.check_output(['python3',str(r/'tools/qmi-test/extract.py'),str(ath)],text=True)
code=r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <sys/redwood_qmi.h>
#include "qmi.h"
#include "tables.inc"
static uint8_t wire[512];static int wire_size,calls;
static int capture_request(struct qmi_handle *h,struct sockaddr_qrtr *s,struct qmi_txn *t,unsigned msg,size_t max,const struct qmi_elem_info *ei,const void *req){
 (void)h;(void)s;(void)t;calls++;wire_size=redwood_qmi_encode(0,msg,42,ei,req,wire,sizeof(wire));assert(wire_size>7 && wire_size<=(int)max+7);return 0;
}
'''+s+r'''
int main(void){
 struct qmi_wlanfw_host_cap_req_msg_v01 req={.num_clients_valid=1,.num_clients=1,.bdf_support_valid=1,.bdf_support=1},saved=req;
 assert(!renoir_qmi_host_cap(NULL,NULL,NULL,QMI_WLANFW_HOST_CAP_REQ_MSG_V01_MAX_LEN,qmi_wlanfw_host_cap_req_msg_v01_ei,&req));
 assert(!memcmp(&req,&saved,sizeof(req)) && calls==1 && wire[3]==0x34);
 unsigned saw=0;
 for(unsigned i=7;i<(unsigned)wire_size;){
  assert(i+3<=(unsigned)wire_size);unsigned tag=wire[i],len=wire[i+1]|wire[i+2]<<8;i+=3;assert(i+len<=(unsigned)wire_size);
  if(tag==0x1f){uint64_t start,size;assert(len==48);memcpy(&start,wire+i,8);memcpy(&size,wire+i+8,8);assert(start==0xa0000000 && size==0x10000000);for(unsigned j=16;j<48;j++)assert(!wire[i+j]);saw|=1;}
  if(tag==0x20){assert(len==4 && wire[i]==2 && !wire[i+1] && !wire[i+2] && !wire[i+3]);saw|=2;}
  if(tag==0x27){assert(len==8);for(unsigned j=0;j<8;j++)assert(!wire[i+j]);saw|=4;}
  if(tag==0x11){assert(len==4 && wire[i]==13 && !wire[i+1] && !wire[i+2] && !wire[i+3]);saw|=8;}
  i+=len;
 }
 assert(saw==15);
 struct qmi_elem_info unterminated[64];memset(unterminated,0,sizeof(unterminated));for(unsigned i=0;i<64;i++)unterminated[i].data_type=QMI_OPT_FLAG;
 assert(renoir_qmi_host_cap(NULL,NULL,NULL,100,unterminated,&req)==-EINVAL && calls==1);
 puts("Renoir HOST_CAP: real wire encoding, DMA range, wake MSI, platform build, caller ownership and descriptor bound passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-hostcap-') as tmp:
 p=Path(tmp);(p/'sys').mkdir()
 for name in ['redwood_qmi.h','redwood_qrtr.h']:(p/'sys'/name).symlink_to(r/'xnu/files/bsd/sys'/name)
 (p/'tables.inc').write_text(tables);(p/'test.c').write_text(code)
 subprocess.run(['clang','-std=gnu11','-Wall','-Wextra','-Wno-unused-variable','-fsanitize=address,undefined','-pthread','-I',str(p),'-I',str(r/'tools/qmi-test/shim'),'-I',str(ath),str(p/'test.c'),str(r/'xnu/files/bsd/dev/redwood_qmi.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
