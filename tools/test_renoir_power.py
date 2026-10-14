#!/usr/bin/env python3
"""Check actual radio supply sequencing and rollback, including partial failure."""
from pathlib import Path
import subprocess
import tempfile
src = (Path(__file__).resolve().parents[1] / 'xnu/files/bsd/dev/redwood_wifi.c').read_text()
start = src.index('struct renoir_radio_votes {')
end = src.index('/* Link-only experiment.', start)
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
static unsigned read_count,write_count,fail_read,fail_write;
static uint32_t state[5][3],initial[5][3];
static void say(const char *s,...) { (void)s; }
static unsigned rail(const char *n) {
 const char *names[]={"smpb10","ldoc11","smpc2","smpb11","smpb12"};
 for(unsigned i=0;i<5;i++) { if(!strcmp(names[i],n)) return i; }
 assert(0);return 0;
}
static bool renoir_rpmh_read(const char *n,uint32_t offset,uint32_t *out) {
 if(++read_count==fail_read) return false;
 *out=state[rail(n)][offset/4]|0x80000000;return true;
}
static bool renoir_vrm_set(const char *n,uint32_t mv,uint32_t enable,uint32_t mode) {
 unsigned i=rail(n);
 state[i][0]=mv;state[i][1]=enable;state[i][2]=mode;
 return ++write_count!=fail_write; /* timeout may have applied the vote */
}
''' + src[start:end] + r'''
int main(void) {
 for(unsigned i=0;i<5;i++) {
  initial[i][0]=i ? 1500+i : 0; initial[i][1]=i&1;initial[i][2]=i;
 }
 for(unsigned fault=0;fault<=30;fault++) {
  memcpy(state,initial,sizeof(state));read_count=write_count=0;
  fail_read=fault<=25 ? fault : 0;fail_write=fault>25 ? fault-25 : 0;
  struct renoir_radio_votes votes;
  bool ok=renoir_radio_power(&votes,true);
  assert(ok==(fault==0));
  if(fault && fault<=15) assert(write_count==0); /* save every rail first */
  assert(renoir_radio_power(&votes,false));
  assert(!memcmp(state,initial,sizeof(state)));
  assert(votes.changed==0);
 }
 puts("Renoir radio power: prior votes preserved; read/write failures roll back partial changes");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-power-') as tmp:
    p = Path(tmp)
    (p / 'test.c').write_text(code)
    subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
