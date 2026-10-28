#!/usr/bin/env python3
"""Exercise real management receive code with delayed/duplicate frame sequences."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'wifi/lx/src/lx_80211.c').read_text()
start = source.index('static void\nmanagement_received(')
receive = source[start:source.index('/*\n * A frame the radio has received', start)]
start = source.index('static void\nanswer_begin(')
begin = source[start:source.index('/* Wait for the access point', start)]
program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
#define ETH_ALEN 6
#define ELEMENTS_MOST 32
#define IEEE80211_STA_ASSOC 3
enum { ANSWER_NONE, ANSWER_AUTHENTICATED, ANSWER_ASSOCIATED, ANSWER_REFUSED, ANSWER_GONE };
struct lx_radio {
 void *sta; struct {uint8_t address[6];} target; struct {uint8_t addr[6];} *vif;
 int reached,work,ba_work;bool joined;int last_error;
 struct {bool start,amsdu;uint16_t size,timeout,ssn;uint8_t token;} ba[8];uint8_t ba_asked;
 int answer;uint8_t answer_frame;uint16_t answer_status,aid;unsigned answer_length;
 uint8_t answer_elements[ELEMENTS_MOST];
};
static unsigned held,wakes,losses;
static void lx_os_lock(void){assert(!held);held=1;}
static void lx_os_unlock(void){assert(held);held=0;}
static void lx_os_wakeup(void *p){assert(held && p);wakes++;}
static int lx_os_option(const char *s){(void)s;return 1;}
static void queue_work(int a,int *b){(void)a;(void)b;}
static void lx_tell(const char *format,...){(void)format;}
static void lx_os_net_link(int up){assert(!up);}
static void lx_os_station_lost(int error){assert(error==ECONNRESET);losses++;}
''' + receive + begin + r'''
int main(void){
 struct lx_radio r={0};typeof(*r.vif) vif={{2}};r.vif=&vif;r.sta=&r;r.target.address[0]=4;
 uint8_t auth[30]={0xb0},assoc[34]={0x10},gone[26]={0xc0};
 memcpy(auth+4,vif.addr,6);memcpy(assoc+4,vif.addr,6);memcpy(gone+4,vif.addr,6);
 memcpy(auth+10,r.target.address,6);memcpy(assoc+10,r.target.address,6);memcpy(gone+10,r.target.address,6);
 auth[26]=2;assoc[28]=0x23;assoc[29]=0xc1;memcpy(assoc+30,"test",4);gone[24]=3;
 answer_begin(&r,0xb0);management_received(&r,assoc,sizeof(assoc));assert(!r.answer && !r.aid && !wakes);
 management_received(&r,auth,sizeof(auth));assert(r.answer==ANSWER_AUTHENTICATED && wakes==1);
 answer_begin(&r,0x10);management_received(&r,auth,sizeof(auth));assert(!r.answer && wakes==1);
 management_received(&r,assoc,29);assert(!r.answer);
 management_received(&r,assoc,sizeof(assoc));assert(r.answer==ANSWER_ASSOCIATED && r.aid==0x123 && r.answer_length==4);
 assert(!memcmp(r.answer_elements,"test",4));unsigned before=wakes;
 management_received(&r,auth,sizeof(auth));assert(r.answer==ANSWER_ASSOCIATED && r.aid==0x123 && wakes==before);
 answer_begin(&r,0x10);assoc[26]=17;management_received(&r,assoc,sizeof(assoc));assert(r.answer==ANSWER_REFUSED && r.answer_status==17);
 answer_begin(&r,0xb0);management_received(&r,assoc,sizeof(assoc));assert(!r.answer);
 auth[10]^=1;management_received(&r,auth,sizeof(auth));assert(!r.answer);auth[10]^=1;
 answer_begin(&r,0x10);r.joined=true;management_received(&r,gone,sizeof(gone));
 assert(r.answer==ANSWER_GONE && !r.joined && losses==1);
 assoc[26]=0;management_received(&r,assoc,sizeof(assoc));assert(r.answer==ANSWER_GONE && r.answer_status==3);
 assert(!held);
}
'''
with tempfile.TemporaryDirectory(prefix='wifi-management-') as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(program)
    subprocess.run(['clang', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('Management replies: delayed auth/assoc isolation, valid AID/elements, rejection, truncation, peer filter and disconnect precedence passed')
