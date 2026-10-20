#!/usr/bin/env python3
"""Run the driver's real reader pin/drain helpers with concurrent host readers."""
from pathlib import Path
import subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_camera.c').read_text()
a=s.index('static bool\nring_pin_read(');b=s.index('/* The session',a)
code=r'''#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <time.h>
#include <stdatomic.h>
#define RING 3
#define PLACE_FREE 0
#define PZERO 0
static pthread_mutex_t ios_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static bool ios_stopping,ios_streaming=true;
static unsigned ios_copies;
static uint64_t ios_frames_done;
static struct {unsigned state;} place[RING];
static atomic_bool drained;
#define lck_mtx_lock pthread_mutex_lock
#define lck_mtx_unlock pthread_mutex_unlock
static int msleep(void *event,pthread_mutex_t *lock,int pri,const char *name,void *timeout){
 (void)event;(void)pri;(void)name;(void)timeout;return pthread_cond_wait(&condition,lock);
}
static void wakeup(void *event){(void)event;pthread_cond_broadcast(&condition);}
'''+s[a:b]+r'''
static void *stop(void *unused){(void)unused;ring_drain_readers();atomic_store(&drained,true);return NULL;}
int main(void){
 for(unsigned trial=0;trial<100;trial++){
  pthread_t worker;atomic_store(&drained,false);ios_stopping=false;ios_streaming=true;
  pthread_mutex_lock(&ios_lock);assert(ring_pin_read());assert(ring_pin_read());
  pthread_mutex_unlock(&ios_lock);assert(!pthread_create(&worker,NULL,stop,NULL));
  for(;;){pthread_mutex_lock(&ios_lock);if(ios_stopping)break;pthread_mutex_unlock(&ios_lock);
   struct timespec wait={0,1000000};nanosleep(&wait,NULL);}
  assert(!ios_streaming && ios_copies==2 && !atomic_load(&drained));
  assert(!ring_pin_read() && ios_copies==2);
  ring_unpin_read();assert(ios_copies==1 && !atomic_load(&drained));
  ring_unpin_read();pthread_mutex_unlock(&ios_lock);
  assert(!pthread_join(worker,NULL));assert(atomic_load(&drained) && ios_copies==0);
  for(unsigned i=0;i<RING;i++)assert(place[i].state==PLACE_FREE);
 }
 puts("Camera lifetime: 100 concurrent stop/copy interleavings; no free before both readers finish, new copies refused during drain");
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
