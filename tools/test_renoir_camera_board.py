#!/usr/bin/env python3
"""Run actual camera board selection and admission checks with host stubs."""
from pathlib import Path
import subprocess
import tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_camera.c').read_text()
a=s.index('enum { SUPPLY_NONE');b=s.index('static unsigned hw_index;',a)
profiles=s[a:b]
a=s.index('void\nredwood_camera_init(');brace=s.index('{',a);end=brace+1;depth=1
while depth:
    depth+=(s[end]=='{')-(s[end]=='}');end+=1
init=s[a:end]
code=r'''#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
static uint32_t level, asked, stream_test, fake_arg;
static bool camera_renoir, fake;
static const char *board, *profile_arg;
static unsigned threads, allocations;
static uintptr_t keep;
static uint64_t keep_bytes;
static struct {unsigned sda,scl;} pmic_bus;
#define PIN_PMIC_SDA (camera_renoir ? 0u : 4u)
#define PIN_PMIC_SCL (camera_renoir ? 1u : 5u)
typedef int thread_t;
#define PAGE_MASK 4095
#define KMA_KOBJECT 1
#define KMA_ZERO 2
#define KMA_DATA 4
#define KERN_SUCCESS 0
#define VM_KERN_MEMORY_IOKIT 0
static int kernel_map;
static bool PE_parse_boot_arg_str(const char *s,char *p,size_t n){if(strcmp(s,"cam_profile")||!profile_arg)return false;snprintf(p,n,"%s",profile_arg);return true;}
static bool redwood_board_is(const char *s){return strcmp(s,board)==0;}
static bool PE_parse_boot_argn(const char *s,void *p,size_t n){(void)n;if(strcmp(s,"cam_fake")==0){*(uint32_t*)p=fake_arg;return true;}if(strcmp(s,"cam_stream_test")==0){*(uint32_t*)p=stream_test;return true;}if(strcmp(s,"cam")==0){*(uint32_t*)p=asked;return true;}return false;}
static int say(const char *s,...){(void)s;return 0;}
static void camera_thread(void){}
static int kernel_thread_start(void(*f)(void),void*p,thread_t*t){(void)f;(void)p;*t=1;threads++;return 0;}
static void thread_deallocate(thread_t t){(void)t;}
static int kmem_alloc_contig(int m,uintptr_t*p,uint64_t n,int mask,int a,int b,int flags,int c){(void)m;(void)n;(void)mask;(void)a;(void)b;(void)flags;(void)c;*p=1;allocations++;return 0;}
'''+profiles+init+r'''
int main(void){
 board="renoir";
 for(asked=5;asked<=6;asked++){redwood_camera_init();assert(level==0 && threads==0 && allocations==0);}
 for(asked=1;asked<=2;asked++){redwood_camera_init();assert(level==asked && sensors==renoir_sensors && pmic_bus.sda==0 && pmic_bus.scl==1);}
 assert(threads==2 && allocations==0);
 for(asked=3;asked<=4;asked++){redwood_camera_init();assert(level==asked);}
 assert(threads==4 && allocations==2);
 assert(sensors[1].vdig.mv==1056 && sensors[1].vaf.ldo==3);
 assert(sensors[2].vana.gpio==176 && sensors[2].vdig.gpio==177);
 assert(sensors[0].csiphy==0 && sensors[1].csiphy==1 && sensors[2].csiphy==5 && sensors[3].csiphy==3);
 for(unsigned i=0;i<SENSOR_COUNT;i++)assert(strncmp(sensors[i].tab,"camera-renoir-",14)==0);
 board="unknown";asked=2;redwood_camera_init();assert(threads==4);
 board="redwood";asked=5;redwood_camera_init();assert(threads==5 && allocations==3);
 /* the default pointer still refers to valid Redwood data before a selection */
 assert(hw==redwood_sensors);
 board="renoir";asked=5;stream_test=1;redwood_camera_init();assert(level==5 && threads==6 && allocations==4);
 assert(sensors[1].gain_unity==32 && sensors[1].gain_max==2048);
 assert(sensors[2].gain_unity==32 && sensors[2].gain_max==512);
 board="unknown";asked=5;fake_arg=1;profile_arg="renoir";redwood_camera_init();
 assert(fake && camera_renoir && sensors==renoir_sensors && threads==7 && allocations==5);
 fake_arg=0;redwood_camera_init();assert(threads==7 && allocations==5);
 asked=2;fake_arg=1;redwood_camera_init();assert(!fake && threads==7 && allocations==5);
 puts("Camera board: Renoir probe admission, cam3/4 admission and cam5 rejection before allocation, isolated tables and unknown-board guard passed");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
