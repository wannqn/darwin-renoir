#!/usr/bin/env python3
"""Check actual security selection and emitted RSN information elements."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'wifi/lx/src/lx_80211.c').read_text()
def part(start, end):
    at = source.index(start)
    return source[at:source.index(end, at)]
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <strings.h>
#define REDWOOD_STA_OPEN 0
#define REDWOOD_STA_WPA2_PSK 1
struct lx_target {unsigned capability,elements_length;uint8_t elements[64];};
''' + part('static const uint8_t *\nelement(', '/* A vendor') + part('static unsigned\nrequest_rsn(', 'static unsigned\nrequest_elements(') + part('static const char *\nprotection(', '/* Pairwise CCMP;') + r'''
int main(void){
 uint8_t out[64],rsn[24];memset(out,0xa5,sizeof(out));memset(rsn,0xa5,sizeof(rsn));
 struct lx_target target={0};unsigned group=9;
 assert(!join_protection(&target,REDWOOD_STA_OPEN,&group) && group==0);
 assert(request_rsn(out,rsn,group)==0 && out[0]==0xa5);
 for(unsigned i=0;i<sizeof(rsn);i++)assert(!rsn[i]);
 assert(join_protection(&target,REDWOOD_STA_WPA2_PSK,&group));
 target.capability=0x10;assert(join_protection(&target,REDWOOD_STA_OPEN,&group));
 for(unsigned cipher=2;cipher<=4;cipher+=2){
  assert(request_rsn(target.elements,rsn,cipher)==22);target.elements_length=22;
  assert(target.elements[0]==48 && target.elements[1]==20 && target.elements[7]==cipher);
  assert(target.elements[13]==4 && target.elements[19]==2);
  assert(!join_protection(&target,REDWOOD_STA_WPA2_PSK,&group) && group==cipher);
  target.capability=0;assert(join_protection(&target,REDWOOD_STA_OPEN,&group));target.capability=0x10;
 }
 assert(join_protection(&target,99,&group));
}
'''
with tempfile.TemporaryDirectory(prefix='wifi-open-') as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(code)
    subprocess.run(['clang', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('Security: explicit open selection omits RSN; protected AP cannot downgrade; WPA2 CCMP/TKIP group selection preserved')
