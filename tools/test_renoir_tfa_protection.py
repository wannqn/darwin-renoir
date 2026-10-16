#!/usr/bin/env python3
"""Run actual NXP RAM-only protection packet construction and fail-closed sequence."""
from pathlib import Path
import tempfile,subprocess
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/renoir_tfa.c').read_text();s=s[s.index('static bool renoir_tfa_dsp_param('):s.index('/* Amplifier control')]
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
static bool board=true,off=true,tfa_protection_ready;
static uint16_t tfa_factory_re25[2]={6232,7624};
static unsigned calls,fail_at;
struct redwood_apr_answer {uint32_t opcode,length,words[16];};
static bool redwood_board_is(const char *s){assert(!strcmp(s,"renoir"));return board;}
static bool renoir_tfa_is_off(void){return off;}
#define redwood_wifi_tell(...) ((void)0)
static bool redwood_adsp_apr(uint8_t svc,uint16_t dst,uint32_t tok,uint32_t op,const void *data,uint32_t len,uint32_t wait,struct redwood_apr_answer *a){
 assert(svc==4 && !dst && !tok && op==0x100ef && wait==1000);
 const uint8_t *p=data;uint32_t w[7];memcpy(w,p,28);
 const uint32_t param[]={0x1000b923,0x1000b920,0x1000b921,0x1000b921};
 assert(calls<4 && w[5]==param[calls]);
 assert((w[0]&0xffff)==(calls==1?0x1005:0x1004));
 assert(w[4]==(calls==1?0x1000b912:0x1000b911) && !w[1] && !w[2] && !w[3]);
 assert(w[6]==(calls<2?4:9) && len==28+w[6] && (w[0]>>16)==12+w[6]);
 const uint8_t bypass[]={0,0,0,0},enable[]={1,0,0,0},mute[]={0,0x81,3,0,0,1,0,0,1};
 const uint8_t calibration[]={0,0x81,5,0x06,0x3b,0x64,0x07,0x9f,0xbe};
 const uint8_t *expected[]={bypass,enable,mute,calibration};
 assert(!memcmp(p+28,expected[calls],w[6]));
 calls++;a->opcode=0x110e8;a->length=8;a->words[0]=op;a->words[1]=calls==fail_at?3:0;return true;
}
"""+s+r"""
int main(void){
 board=false;assert(!renoir_tfa_configure_protection() && !calls);board=true;
 off=false;assert(!renoir_tfa_configure_protection() && !calls);off=true;
 tfa_factory_re25[0]=0;assert(!renoir_tfa_configure_protection() && !calls);tfa_factory_re25[0]=6232;
 for(unsigned f=0;f<=4;f++){calls=0;fail_at=f;bool ok=renoir_tfa_configure_protection();assert(ok==(f==0));assert(calls==(f?f:4));}
}
"""
with tempfile.TemporaryDirectory(prefix='tfa-protection-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('TFA DSP: board/off/calibration guards, exact NXP module IDs, muted channels, Q16 factory values and refusal sequence passed')
