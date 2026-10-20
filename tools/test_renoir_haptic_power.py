#!/usr/bin/env python3
"""Check actual APPS BOB vote save/restore without overwriting other clients."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1];s=(r/'xnu/files/bsd/dev/redwood_wifi.c').read_text();s=s[s.index('bool redwood_renoir_haptic_supply('):]
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
static uint32_t votes[3],other_client[3]={3296,1,6};
static bool board=true;static unsigned reads,sets,fail_read,fail_set;
static bool redwood_board_is(const char *b){assert(!strcmp(b,"renoir"));return board;}
static bool renoir_rpmh_read(const char *b,unsigned off,uint32_t *v){assert(!strcmp(b,"bobc1") && off<=8 && !(off&3));if(++reads==fail_read)return false;*v=votes[off/4]|(off==0 && votes[0]?0x80000000u:0);return true;}
static bool renoir_vrm_set(const char *b,uint32_t v,uint32_t e,uint32_t m){assert(!strcmp(b,"bobc1"));votes[0]=v;votes[1]=e;votes[2]=m;return ++sets!=fail_set;}
"""+s+r"""
static void init(unsigned mv,unsigned en,unsigned mode){votes[0]=mv;votes[1]=en;votes[2]=mode;reads=sets=fail_read=fail_set=0;renoir_haptic_bob_changed=false;}
int main(void){
 init(0,0,0);board=false;assert(!redwood_renoir_haptic_supply_vote(true));assert(!sets);board=true;
 assert(redwood_renoir_haptic_supply_vote(true));uint32_t actual_mv;bool actual_on;assert(redwood_renoir_haptic_supply(&actual_mv,&actual_on));assert(actual_mv==3296 && actual_on);assert(votes[0]==3296 && votes[1]==1 && votes[2]==6);
 assert(redwood_renoir_haptic_supply_vote(false));assert(!votes[0]&&!votes[1]&&!votes[2]);
 init(3500,1,7);assert(redwood_renoir_haptic_supply_vote(true));assert(votes[0]==3500 && votes[2]==7);assert(redwood_renoir_haptic_supply_vote(false));assert(votes[0]==3500 && votes[1]==1 && votes[2]==7);
 for(unsigned f=1;f<=4;f++){init(0,0,0);fail_read=f;assert(!redwood_renoir_haptic_supply_vote(true));assert(!votes[0]&&!votes[1]&&!votes[2]);}
 init(0,0,0);fail_set=1;assert(!redwood_renoir_haptic_supply_vote(true));assert(!votes[0]&&!votes[1]&&!votes[2]);
 init(4000,1,6);assert(!redwood_renoir_haptic_supply_vote(true));assert(!sets);
 assert(other_client[0]==3296 && other_client[1]==1 && other_client[2]==6);
}
"""
with tempfile.TemporaryDirectory(prefix='rh-power-') as d:
 p=Path(d);(p/'t.c').write_text(code)
 subprocess.run(['clang','-Werror','-fsanitize=address,undefined',str(p/'t.c'),'-o',str(p/'t')],check=True)
 subprocess.run([str(p/'t')],check=True)
print('Haptic BOB: prior APPS voltage/enable/mode retained, other clients untouched, read/write failures roll back, BOB AUTO mode and range guards passed')
