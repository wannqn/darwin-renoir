#!/usr/bin/env python3
"""Execute real silent MI2S clock/start/stop test with injected APR failures."""
from pathlib import Path
import tempfile,subprocess
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/renoir_tfa.c').read_text();s=s[s.index('static bool renoir_afe_command('):]
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#define TFA_TLMM 0x0f100000
#define TFA_CFG(n) (0x1000u*(n))
#define TFA_IO(n) (TFA_CFG(n)+4)
#define NSEC_PER_USEC 1000
static uintptr_t tfa_tlmm=1;
static bool tfa_probe_complete=true,tfa_amplifiers_off=true;
static uint32_t regs[0x100000/4];
static unsigned calls,fail_at,seen[16],clock_enable[16];
struct redwood_apr_answer {uint32_t opcode,length,words[16];};
static uintptr_t ml_io_map(uintptr_t a,unsigned n){assert(a==TFA_TLMM && n==0x100000);return 1;}
static uint32_t tr(unsigned off){assert(off<0x100000);return regs[off/4];}
static void tw(unsigned off,uint32_t v){assert(off<0x100000);regs[off/4]=v;}
static void delay_for_interval(unsigned n,unsigned unit){assert(n==1 && unit==1000);regs[TFA_IO(120)/4]^=1;regs[TFA_IO(122)/4]^=1;}
#define redwood_wifi_tell(...) ((void)0)
static bool redwood_adsp_apr(uint8_t svc,uint16_t dst,uint32_t tok,uint32_t op,const void *buf,uint32_t len,uint32_t wait,struct redwood_apr_answer *a){
 assert(svc==4 && !dst && !tok && wait==1000 && calls<16);
 seen[calls]=op;
 if(op==0x100f3){
  assert(len==48);uint32_t w[12];memcpy(w,buf,len);
  assert(w[0]==32 && !w[1] && !w[2] && !w[3]);
  assert(w[4]==0x1028f && w[5]==0x10290 && w[6]==20 && w[7]==1);
  assert(w[8]==0x104 && w[9]==6144000 && w[10]==1);
  assert(w[11]<=1);clock_enable[calls]=w[11];
 }else{
  const uint16_t *v=buf;assert(len==4 && !v[1] && (v[0]==0x1004||v[0]==0x1005));
  assert(op==0x100e5 || op==0x100e6);
  /* Actual mux selections, including SD1 on GPIO124 mux3. */
  assert(regs[TFA_CFG(120)/4]==0xc4 && regs[TFA_CFG(124)/4]==0xcc);
 }
 calls++;a->opcode=0x110e8;a->length=8;a->words[0]=op;
 a->words[1]=(calls==fail_at)?2:0;return calls!=fail_at;
}
"""+s+r"""
int main(void){
 tfa_amplifiers_off=false;renoir_afe_clock_test();assert(!calls);
 tfa_amplifiers_off=true;tfa_probe_complete=false;renoir_afe_clock_test();assert(!calls);
 tfa_probe_complete=true;
 const unsigned pins[]={120,122,121,124};
 for(unsigned failure=0;failure<=6;failure++){
  calls=0;fail_at=failure;memset(regs,0,sizeof(regs));
  for(unsigned i=0;i<4;i++){regs[TFA_CFG(pins[i])/4]=0x321+i;regs[TFA_IO(pins[i])/4]=2;}
  renoir_afe_clock_test();
  for(unsigned i=0;i<4;i++){assert(regs[TFA_CFG(pins[i])/4]==0x321+i);assert(regs[TFA_IO(pins[i])/4]==2);}
  assert(seen[0]==0x100f3 && clock_enable[0]==1);
  assert(seen[calls-1]==0x100f3 && clock_enable[calls-1]==0);
  if(failure==1)assert(calls==2);
  else if(failure==2){assert(calls==4 && seen[2]==0x100e6);}
  else assert(calls==6 && seen[3]==0x100e6 && seen[4]==0x100e6);
 }
}
"""
with tempfile.TemporaryDirectory(prefix='afe-clock-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('MI2S clock: 6.144MHz ABI, correct pin mux, RX/TX stop after every injected failure, clock-off and pin restoration passed')
