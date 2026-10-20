#!/usr/bin/env python3
"""Fault injection against the actual bounded-pattern haptic register core."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1]
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
#include "renoir_haptic_core.h"
static uint8_t regs[65536],original[65536];
static unsigned calls,fail_at,writes;
static bool get(uint16_t a,uint8_t *v){if(++calls==fail_at)return false;*v=regs[a];return true;}
static bool put(uint16_t a,uint8_t v){assert(rhh_allowed(a));if(++calls==fail_at)return false;regs[a]=v;writes++;return true;}
static const struct rhh_bus bus={get,put};
static void init(void){memset(regs,0,sizeof(regs));regs[0xf004]=regs[0xf104]=0x15;regs[0xf005]=0x0a;regs[0xf105]=0x0b;regs[0xf001]=regs[0xf101]=2;regs[0xf048]=49;memcpy(original,regs,sizeof(regs));calls=fail_at=writes=0;}
int main(void){
 init();struct rhh_state s={0};assert(!rhh_prepare(&s,&bus,3296,false));assert(!writes);
 assert(!rhh_prepare(&s,&bus,2800,true));assert(!writes);
 assert(!rhh_prepare(&s,&bus,4000,true));assert(!writes);
 init();regs[0xf04c]=0x81;assert(!rhh_prepare(&s,&bus,3296,true));assert(!writes);
 init();assert(rhh_prepare(&s,&bus,3296,true));unsigned n=calls;assert(regs[0xf048]==33);assert(!(regs[0xf04c]&0x80));
 assert(rhh_start(&s,&bus));assert(regs[0xf04c]==0x82);assert(rhh_stop(&s,&bus));assert(rhh_restore(&s,&bus));assert(!memcmp(regs,original,sizeof(regs)));
 for(unsigned f=1;f<=n;f++){init();memset(&s,0,sizeof(s));fail_at=f;bool ok=rhh_prepare(&s,&bus,3296,true);assert(!ok);fail_at=0;assert(rhh_restore(&s,&bus));assert(!memcmp(regs,original,sizeof(regs)));}
 init();memset(&s,0,sizeof(s));assert(rhh_prepare(&s,&bus,3296,true));regs[0xf00c]=4;assert(!rhh_start(&s,&bus));assert(!(regs[0xf04c]&0x80));regs[0xf00c]=0;assert(rhh_restore(&s,&bus));
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-haptic-core-') as d:
 p=Path(d);(p/'t.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined','-I'+str(r/'xnu/files/bsd/dev'),str(p/'t.c'),'-o',str(p/'t')],check=True)
 subprocess.run([str(p/'t')],check=True)
print('PM8350B finite pattern: external supply/type/idle/fault guards, 1650mV ceiling, register allowlist and rollback after every startup failure passed')
