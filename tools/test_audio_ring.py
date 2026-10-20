#!/usr/bin/env python3
"""Stress the real PCM producer/consumer, including uint32 index rollover."""
from pathlib import Path
import subprocess,tempfile,re
r=Path(__file__).resolve().parents[1];s=(r/'xnu/files/bsd/dev/redwood_sound.c').read_text()
a=s.index('static uint32_t\nios_sink(');b=s.index('static uint32_t guard_periods;',a)
c=s.index('static void\nperiod_fill_ios(');d=s.index('static void\nfeeder_thread(',c)
body=s[a:b]+s[c:d]
body=re.sub(r'__asm__ volatile \("dc cvac, %0".*?;', '(void)line;',body)
body=body.replace('__asm__ volatile ("dsb sy" ::: "memory");','__sync_synchronize();')
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
#include <pthread.h>
#include <sched.h>
typedef uintptr_t vm_offset_t;
#define RING_FRAMES 1024
#define PERIOD_FRAMES 64
#define PERIOD_BYTES (PERIOD_FRAMES*4)
#define SILENCE 8
#define OSMemoryBarrier() __sync_synchronize()
static int16_t ring[RING_FRAMES*2],period_buffer[2048];
static uintptr_t buffer=(uintptr_t)period_buffer;
static volatile uint32_t ring_head,ring_tail,ios_peak;
static volatile uint64_t last_sound_us;
static uint64_t ios_frames,fed_frames,silent_frames;
static unsigned guard_periods,level;static bool sound_renoir;
static uint32_t received;
#define TOTAL 1000000u
static uint64_t now_us(void){return 0;}
static void redwood_guard_process(int16_t *p,unsigned n){(void)p;(void)n;}
static bool redwood_audio_recording_fed(void){return true;}
static void redwood_audio_record_fed(int16_t *p,unsigned n){
 for(unsigned i=0;i<n;i++){uint32_t seq=(uint16_t)p[2*i]|((uint32_t)(uint16_t)p[2*i+1]<<16);assert(seq==received++);}
}
static void renoir_tfa_scale_pcm(int16_t *p,unsigned n){(void)p;(void)n;}
"""+body+r"""
static void *produce(void *unused){
 (void)unused;unsigned sent=0;
 while(sent<TOTAL){int16_t p[194];unsigned n=TOTAL-sent>97?97:TOTAL-sent;
  for(unsigned i=0;i<n;i++){p[2*i]=(int16_t)(sent+i);p[2*i+1]=(int16_t)((sent+i)>>16);}
  sent+=ios_sink(p,n);sched_yield();
 }return 0;
}
static void *consume(void *unused){(void)unused;while(received<TOTAL){period_fill_ios(0);sched_yield();}return 0;}
int main(void){ring_head=ring_tail=UINT32_MAX-17;pthread_t p,c;assert(!pthread_create(&p,0,produce,0));assert(!pthread_create(&c,0,consume,0));pthread_join(p,0);pthread_join(c,0);assert(received==TOTAL);assert(ring_head==ring_tail);assert(ios_frames==TOTAL && fed_frames==TOTAL);}
"""
with tempfile.TemporaryDirectory(prefix='audio-ring-') as d:
 p=Path(d);(p/'t.c').write_text(code)
 subprocess.run(['clang','-O2','-Werror','-pthread','-fsanitize=address,undefined',str(p/'t.c'),'-o',str(p/'t')],check=True)
 subprocess.run([str(p/'t')],check=True)
print('PCM ring: actual producer/consumer, one million stereo frames, concurrent refill and uint32 rollover passed')
