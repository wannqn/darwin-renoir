#!/usr/bin/env python3
"""Exercise actual board-specific Wi-Fi defaults and explicit overrides."""
from pathlib import Path
import subprocess, tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'xnu/files/bsd/dev/redwood_wifi.c').read_text()
a=s.index('uint32_t\nredwood_wifi_option(')
b=s.index('/* ---- register access',a)
code=r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
static bool whole, quiet, renoir;
static const char *option;
static uint32_t value;
static bool redwood_board_is(const char *name) { return renoir && !strcmp(name,"renoir"); }
static bool PE_parse_boot_argn(const char *name,void *out,unsigned size) {
 assert(size==4);
 if(!option || strcmp(name,option)) return false;
 *(uint32_t *)out=value;return true;
}
"""+s[a:b]+r"""
int main(void) {
 whole=true;quiet=true;renoir=true;
 assert(redwood_wifi_option("wifi_irq")==0);
 option="wifi_irq";value=1;assert(redwood_wifi_option(option)==0);
 renoir=false;assert(redwood_wifi_option(option)==1);
 value=0;assert(redwood_wifi_option(option)==0);
 option=NULL;assert(redwood_wifi_option("wifi_irq")==1);
 renoir=true;assert(redwood_wifi_option("wifi_ba")==1);
 assert(redwood_wifi_option("wifi_wide")==1);
 option="wifi_wide";value=0;assert(redwood_wifi_option(option)==0);
 option="wifi_quiet";value=0;assert(redwood_wifi_option(option)==0);
 option=NULL;assert(redwood_wifi_option("wifi_quiet")==1);
 assert(redwood_wifi_option("wifi_station")==1);
 whole=false;assert(redwood_wifi_option("wifi_station")==0);
 return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-options-') as tmp:
 p=Path(tmp);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Wi-Fi options: Renoir rejects AHB IRQ even when requested; Redwood defaults, BA/width and explicit overrides passed')
