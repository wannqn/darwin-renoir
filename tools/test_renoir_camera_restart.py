#!/usr/bin/env python3
"""Execute actual read admission across a drain/restart, including terminal faults."""
from pathlib import Path
import subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_camera.c').read_text()
a=s.index('static int\ncamdev_read_prepare(');b=s.index('\n}',a)+2
code=r"""
#include <stdbool.h>
#include <errno.h>
#include <assert.h>
#include <stdio.h>
static bool broken,ios_streaming,ios_wanted,ios_stopping,ios_open;
static unsigned wakes;
static void wakeup(void*p){assert(p==&ios_open);wakes++;}
"""+s[a:b]+r"""
int main(void){
 ios_open=true;
 assert(!camdev_read_prepare() && ios_wanted && wakes==1);
 assert(!camdev_read_prepare() && wakes==1);
 ios_streaming=true;ios_wanted=false;assert(!camdev_read_prepare() && !ios_wanted && wakes==1);
 /* Stop drains the old ring; its replacement cannot exist until requested. */
 ios_streaming=false;ios_stopping=true;
 assert(camdev_read_prepare()==EAGAIN && ios_wanted && wakes==2);
 assert(camdev_read_prepare()==EAGAIN && wakes==2);
 /* serve_ios consumes the request, then ring_alloc admits readers again. */
 ios_wanted=false;ios_stopping=false;ios_streaming=true;
 assert(!camdev_read_prepare() && !ios_wanted && wakes==2);
 broken=true;ios_stopping=true;ios_streaming=false;
 assert(camdev_read_prepare()==EIO && !ios_wanted && wakes==2);
 puts("Camera restart: initial request, active read, drain queues one restart without reading freed memory, new ring resumes, terminal EIO preserved");
}
"""
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=5)
