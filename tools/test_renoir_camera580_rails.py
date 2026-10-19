#!/usr/bin/env python3
"""Exercise the actual Renoir ARC vote ownership/rollback logic."""
from pathlib import Path
import subprocess
import tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_camera.c').read_text()
a=s.index('static bool renoir_arc_changed');b=s.index('/* CX and MX at the camera',a)
code=r'''#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <stddef.h>
#define CX_LEVEL 128
#define MX_LEVEL 192
#define CAMERA_TCS 1
#define RSC_TCS(n) 0
static uintptr_t rsc;
static bool leaving,rails_voted;
static int locks,operations,fail_at;
static uint32_t votes[2];
struct rcam_io {void*context;bool(*put)(void*,uint32_t,uint32_t,bool);bool(*wait)(void*,uint32_t,uint32_t,uint32_t,uint32_t);uint32_t(*get)(void*,uint32_t);};
static bool rcam_arc_put(void*c,uint32_t r,uint32_t v,bool b){(void)c;(void)r;(void)v;(void)b;return true;}
static bool rcam_arc_wait(void*c,uint32_t r,uint32_t m,uint32_t w,uint32_t u){(void)c;(void)r;(void)m;(void)w;(void)u;return true;}
static uint32_t rcam_arc_get(void*c,uint32_t r){(void)c;(void)r;return 0;}
static int rail_position(const char*n,unsigned l,uint32_t*a){(void)l;unsigned i=strcmp(n,"mx.lvl")==0;*a=0x30000+4*i;return i?6:4;}
static void redwood_rpmh_lock(void){assert(locks==0);locks++;}
static void redwood_rpmh_unlock(void){assert(locks==1);locks--;}
static int say(const char*s,...){(void)s;return 0;}
static bool rcam_tcs_transfer(const struct rcam_io*io,uint32_t a,bool write,uint32_t*v){
 (void)io;assert(locks==1);unsigned i=(a-0x30000)/4;assert(i<2);
 operations++;
 if(write)votes[i]=*v; /* even a timed-out write may have been applied */
 if(operations==fail_at)return false;
 if(!write)*v=votes[i]|0x80000000u;
 return true;
}
'''+s[a:b]+r'''
static void setup(void){
 votes[0]=1;votes[1]=2;operations=0;fail_at=0;locks=0;
 memset(renoir_arc_changed,0,sizeof(renoir_arc_changed));rails_voted=false;
}
int main(void){
 setup();votes[0]=9;assert(renoir_camera_rails(true));assert(votes[0]==9&&votes[1]==6);
 assert(!renoir_camera_rails(true));assert(renoir_camera_rails(false));assert(votes[0]==9&&votes[1]==2&&!rails_voted);
 for(int f=1;f<=4;f++){
  setup();fail_at=f;assert(!renoir_camera_rails(true));fail_at=0;
  assert(renoir_camera_rails(false));assert(votes[0]==1&&votes[1]==2&&locks==0&&!rails_voted);
 }
 setup();assert(renoir_camera_rails(true));votes[0]=10;
 assert(renoir_camera_rails(false));assert(votes[0]==10&&votes[1]==2);
 for(int f=1;f<=4;f++){
  setup();assert(renoir_camera_rails(true));operations=0;fail_at=f;
  assert(!renoir_camera_rails(false));fail_at=0;
  assert(renoir_camera_rails(false));assert(votes[0]==1&&votes[1]==2&&!rails_voted&&locks==0);
 }
 puts("Titan580 rails: saved higher vote, ARC status-bit decode, partial/timed-out writes, restore failures, later-client preservation and shared lock passed");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
