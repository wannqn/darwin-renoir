#!/usr/bin/env python3
"""Run actual board-specific charge conversion, including u32 overflow edge."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/redwood_adsp.c').read_text()
a=s.index('static uint32_t\nbattmgr_charge_uah(');b=s.index('static void\nbattmgr_thread(',a)
code='#include <stdint.h>\n#include <stdbool.h>\n#include <assert.h>\nstatic bool renoir;\nstatic bool redwood_board_is(const char *s){(void)s;return renoir;}\n'+s[a:b]+"""
int main(void){
 assert(battmgr_charge_uah(100128000)==100128000);
 renoir=true;assert(battmgr_charge_uah(100128000)==1001280);
 assert(battmgr_charge_uah(0)==0);
 assert(battmgr_charge_uah(149)==1);assert(battmgr_charge_uah(150)==2);
 assert(battmgr_charge_uah(UINT32_MAX)==42949673);
}
"""
with tempfile.TemporaryDirectory(prefix='battmgr-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Battery manager: Renoir charge counter units, rounding, overflow, Redwood unchanged passed')
