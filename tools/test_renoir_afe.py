#!/usr/bin/env python3
"""Execute Renoir config-only AFE probing with a fake APR transport."""
from pathlib import Path
import tempfile,subprocess
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/renoir_tfa.c').read_text()
s=s[s.index('struct renoir_i2s_config {'):s.index('/* Bounded, silent')]
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
struct redwood_apr_answer { uint32_t opcode,length,words[16]; };
static bool renoir=true,enabled=true,fail=false,short_reply=false;
static unsigned calls;
static void renoir_afe_clock_test(void){assert(0);}
static bool redwood_board_is(const char *s){assert(!strcmp(s,"renoir"));return renoir;}
static bool PE_parse_boot_argn(const char *s,void *v,unsigned n){assert(!strcmp(s,"renoir_afe_probe") && n==4);*(uint32_t*)v=enabled;return true;}
#define redwood_wifi_tell(...) ((void)0)
static bool redwood_adsp_apr(uint8_t,uint16_t,uint32_t,uint32_t,const void*,uint32_t,uint32_t,struct redwood_apr_answer*);
"""+s+r"""
static bool redwood_adsp_apr(uint8_t svc,uint16_t dst,uint32_t token,uint32_t op,const void *buf,uint32_t len,uint32_t wait,struct redwood_apr_answer *a){
 assert(svc==4 && dst==0 && token==0 && op==0x100ef && len==48 && wait==1000);
 const struct renoir_afe_config_packet *p=buf;
 assert(p->port==(calls==0?0x1004:0x1005) && p->bytes==32);
 assert(!p->address_low && !p->address_high && !p->map_handle);
 assert(p->module==0x1020c && p->param==0x1020d && p->size==20 && !p->reserved);
 assert(p->config.version==1 && p->config.bits==24 && p->config.rate==96000);
 assert(p->config.line==(calls==0?2:1) && p->config.stereo==1 && p->config.ws_internal==1);
 assert(!p->config.format && !p->config.reserved);
 calls++;a->opcode=0x110e8;a->length=short_reply?4:8;a->words[0]=op;a->words[1]=fail?2:0;return true;
}
int main(void){
 renoir=false;renoir_tfa_dsp_up();assert(!calls);
 renoir=true;enabled=false;renoir_tfa_dsp_up();assert(!calls);
 enabled=true;renoir_tfa_dsp_up();assert(calls==2);
 calls=0;fail=true;renoir_tfa_dsp_up();assert(calls==1);
 calls=0;fail=false;short_reply=true;renoir_tfa_dsp_up();assert(calls==1);
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-afe-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Renoir AFE: real RX/TX config ABI, board/boot guards, refusal/short response, no start/clock/amp commands passed')
