#!/usr/bin/env python3
"""Exercise the actual Lite580 ring target selector under reader/producer states."""
from pathlib import Path
import subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_camera.c').read_text()
a=s.index('static int\nring_next_place(');b=s.index('\nstatic void\nios_session(',a)
code='''#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#define RING 3
enum {PLACE_FREE,PLACE_WRITING,PLACE_READY,PLACE_READING};
static struct {unsigned state;uint64_t sequence;} place[RING];
'''+s[a:b]+'''
int main(void){
 for(int writing=0;writing<RING;writing++){
  for(unsigned a=0;a<4;a++)for(unsigned b=0;b<4;b++){
   int x=(writing+1)%RING,y=(writing+2)%RING;
   place[writing].state=PLACE_READY;place[writing].sequence=99;
   place[x].state=a;place[x].sequence=1;place[y].state=b;place[y].sequence=2;
   int n=ring_next_place(writing);
   if(a==PLACE_READING&&b==PLACE_READING)assert(n==-1);
   else {assert(n>=0&&n!=writing&&place[n].state!=PLACE_READING);
    assert(n==(a==PLACE_READING?y:x));}
   place[x].sequence=3;n=ring_next_place(writing);
   if(a!=PLACE_READING&&b!=PLACE_READING)assert(n==y);
  }
 }
 puts("Lite580 ring: current frame excluded, in-flight readers excluded, oldest slot selected, exhausted ring rejected");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
