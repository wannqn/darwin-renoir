#!/usr/bin/env python3
"""Exercise the real station-worker join branch, fallback delay and cancellation."""
from pathlib import Path
import subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_sta.c').read_text()
a=s.index('} else if (do_join) {')+len('} else if (do_join) {')
b=s.index('} else if (do_scan)',a)
code=r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define THREAD_UNINT 0
#define THREAD_CONTINUE_NULL 0
#define NSEC_PER_SEC 1000000000u
#define REDWOOD_STA_JOIN_DONE 1
#define REDWOOD_STA_LINK 2
#define bzero(p,n) memset(p,0,n)
typedef void *event_t;
struct request { unsigned ssid_length; char secret[16]; };
static struct request join,standing,asked_join_what,fallback;
static bool asked_join,asked_leave,asked_power;
static int sta_lock,locked,result,mode,delays,done,linked;
static void lck_mtx_lock(int *p){(void)p;assert(!locked);locked=1;}
static void lck_mtx_unlock(int *p){(void)p;assert(locked);locked=0;}
static void redwood_apple80211_event(int event,int status){
 assert(!locked);if(event==REDWOOD_STA_JOIN_DONE) done=status;else linked=status;
}
static void assert_wait_timeout(event_t e,int flags,unsigned n,unsigned units){
 (void)e;(void)flags;assert(!locked && n==1 && units==NSEC_PER_SEC);delays++;
}
static void thread_block(int c){
 (void)c;assert(!locked);if(mode==1) asked_power=true;
 if(mode==2){asked_join=true;asked_join_what.ssid_length=9;}
}
static int join_station(const struct request *q){(void)q;return result;}
static const struct {int (*join)(const struct request *);} operations={join_station},*ops=&operations;
static void run_join(void){int error;
"""+s[a:b]+r"""
}
static void reset(void){
 asked_join=asked_leave=asked_power=false;mode=delays=done=linked=0;
 memset(&fallback,0,sizeof(fallback));fallback.ssid_length=11;fallback.secret[0]='x';
 memset(&asked_join_what,0,sizeof(asked_join_what));
}
int main(void){
 reset();result=80;run_join();assert(done==80 && delays==1 && asked_join);
 assert(standing.ssid_length==11 && asked_join_what.secret[0]=='x' && !fallback.ssid_length);
 result=0;asked_join=false;run_join();assert(done==0 && linked==1 && delays==1);
 reset();result=80;mode=1;run_join();assert(asked_power && !asked_join && !fallback.ssid_length);
 reset();result=80;mode=2;run_join();assert(asked_join && asked_join_what.ssid_length==9);
 assert(!locked);return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-sta-fallback-') as tmp:
 p=Path(tmp);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Station fallback: error published before unlocked backoff, successful reconnect updates result, pending power/join wins, secret cleared')
