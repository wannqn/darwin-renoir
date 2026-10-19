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
static uint32_t level, asked;
static bool camera_renoir;
static const char *board;
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
static bool redwood_board_is(const char *s){return strcmp(s,board)==0;}
static bool PE_parse_boot_argn(const char *s,void *p,size_t n){(void)n;if(strcmp(s,"cam")==0){*(uint32_t*)p=asked;return true;}return false;}
static int say(const char *s,...){(void)s;return 0;}
static void camera_thread(void){}
static int kernel_thread_start(void(*f)(void),void*p,thread_t*t){(void)f;(void)p;*t=1;threads++;return 0;}
static void thread_deallocate(thread_t t){(void)t;}
static int kmem_alloc_contig(int m,uintptr_t*p,uint64_t n,int mask,int a,int b,int flags,int c){(void)m;(void)n;(void)mask;(void)a;(void)b;(void)flags;(void)c;*p=1;allocations++;return 0;}
'''+profiles+init+r'''
int main(void){
 board="renoir";
 for(asked=3;asked<=6;asked++){redwood_camera_init();assert(level==0 && threads==0 && allocations==0);}
 for(asked=1;asked<=2;asked++){redwood_camera_init();assert(level==asked && sensors==renoir_sensors && pmic_bus.sda==0 && pmic_bus.scl==1);}
 assert(threads==2 && allocations==0);
 assert(sensors[1].vdig.mv==1056 && sensors[1].vaf.ldo==3);
 assert(sensors[2].vana.gpio==176 && sensors[2].vdig.gpio==177);
 assert(sensors[0].csiphy==0 && sensors[1].csiphy==1 && sensors[2].csiphy==5 && sensors[3].csiphy==3);
 for(unsigned i=0;i<SENSOR_COUNT;i++)assert(strncmp(sensors[i].tab,"camera-renoir-",14)==0);
 board="unknown";asked=2;redwood_camera_init();assert(threads==2);
 board="redwood";asked=5;redwood_camera_init();assert(threads==3 && allocations==1);
 /* the default pointer still refers to valid Redwood data before a selection */
 assert(hw==redwood_sensors);
 puts("Camera board: Renoir probe admission, capture rejection before allocation, isolated tables and unknown-board guard passed");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
