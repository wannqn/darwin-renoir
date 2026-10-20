#!/usr/bin/env python3
"""Exercise actual board-dispatch and ARC journal, not only register helpers."""
from pathlib import Path
import subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_camera.c').read_text()
def function(name):
 a=s.index('static bool\n'+name+'(');b=s.index('{',a);depth=1;e=b+1
 while depth:
  depth+=(s[e]=='{')-(s[e]=='}');e+=1
 return s[a:e]
code=r"""
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#define CX_LEVEL 1
#define MX_LEVEL 1
#define CAMERA_TCS 3
#define RSC_TCS(n) (0x100u*(n))
static uintptr_t rsc;
static bool camera_renoir=true,leaving,rails_voted,renoir_arc_changed[2];
static uint32_t renoir_arc_old[2],renoir_arc_vote[2],values[2]={1,2};
static unsigned reads,writes,redwood_writes,locks;
struct rcam_io{void*context;void*put;void*wait;void*get;};
static void *rcam_arc_put,*rcam_arc_wait,*rcam_arc_get;
static int rail_position(const char*n,unsigned level,uint32_t*a){(void)level;bool mx=!strcmp(n,"mx.lvl");*a=0x30000u+4u*mx;return mx?4:3;}
static bool rcam_tcs_transfer(struct rcam_io*i,uint32_t address,bool write,uint32_t*v){
 (void)i;unsigned n=(address-0x30000)/4;assert(n<2);assert(reads+writes<100);
 if(write){values[n]=*v;writes++;}else{*v=values[n];reads++;}return true;
}
static void redwood_rpmh_lock(void){locks++;}
static void redwood_rpmh_unlock(void){assert(locks);locks--;}
static void say(const char*s,...){(void)s;}
static bool rpmh_write(unsigned n,const uint32_t*a,const uint32_t*v){(void)n;(void)a;(void)v;redwood_writes++;return true;}
"""+function('renoir_camera_rails')+function('rails')+r"""
int main(void){
 assert(rails(true));assert(values[0]==3 && values[1]==4 && rails_voted && writes==2 && !redwood_writes && !locks);
 assert(!rails(true));assert(writes==2);
 assert(rails(false));assert(values[0]==1 && values[1]==2 && !rails_voted && writes==4);
 assert(rails(true));values[0]=7;assert(rails(false));assert(values[0]==7 && values[1]==2 && !rails_voted);
 camera_renoir=false;assert(rails(true));assert(redwood_writes==1);
 puts("Camera rails: Renoir dispatch terminates, ARC votes/restoration and later-client ownership preserved; Redwood isolated");
}
"""
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=5)
