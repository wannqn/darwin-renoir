#!/usr/bin/env python3
"""Exercise actual station key installation for CCMP and TKIP GTK."""
from pathlib import Path
import subprocess,tempfile
r=Path(__file__).resolve().parents[1]
s=(r/'wifi/lx/src/lx_80211.c').read_text();a=s.index('static struct ieee80211_key_conf *\nkey_set(');b=s.index('/* The access point has changed',a);s=s[a:b]
code=r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
#define GFP_KERNEL 0
#define WLAN_CIPHER_SUITE_TKIP 2
#define WLAN_CIPHER_SUITE_CCMP 4
#define IEEE80211_KEY_FLAG_PAIRWISE 1
#define SET_KEY 1
#define DISABLE_KEY 0
struct ieee80211_key_conf{unsigned cipher;uint8_t keyidx,keylen,iv_len,icv_len;unsigned flags;int link_id;uint8_t key[];};
struct lx_radio{unsigned group_cipher;struct{unsigned group_length;}wpa;struct{int mtx;}*wiphy;struct{int(*set_key)(void *,int,void *,void *,struct ieee80211_key_conf *);}*ops;int hw;void *vif,*sta;};
static unsigned locked,allocated,calls;static bool no_memory;static int driver_error;
static void *kzalloc(size_t n,int flags){(void)flags;if(no_memory)return NULL;allocated++;return calloc(1,n);}
static void kfree(struct ieee80211_key_conf *p){for(unsigned i=0;i<p->keylen;i++)assert(!p->key[i]);assert(allocated);allocated--;free(p);}
static void mutex_lock(int *p){(void)p;assert(!locked);locked=1;}
static void mutex_unlock(int *p){(void)p;assert(locked);locked=0;}
static int install(void *h,int cmd,void *v,void *sta,struct ieee80211_key_conf *c){(void)h;(void)v;(void)sta;assert(locked && c);calls++;return cmd==SET_KEY ? driver_error : 0;}
'''+s+r'''
int main(void){
 struct lx_radio radio={0};typeof(*radio.wiphy) wiphy={0};typeof(*radio.ops) ops={.set_key=install};radio.wiphy=&wiphy;radio.ops=&ops;radio.sta=&radio;
 uint8_t material[32];for(unsigned i=0;i<32;i++)material[i]=i;int error;
 radio.group_cipher=4;radio.wpa.group_length=16;
 struct ieee80211_key_conf *c=key_set(&radio,material,1,false,&error);assert(c && !error && c->cipher==4 && c->keylen==16 && c->icv_len==8 && !memcmp(c->key,material,16));key_drop(&radio,&c,false);assert(!c);
 radio.group_cipher=2;radio.wpa.group_length=32;
 c=key_set(&radio,material,2,false,&error);assert(c && !error && c->cipher==2 && c->keylen==32 && c->icv_len==4 && !memcmp(c->key,material,16));
 assert(!memcmp(c->key+16,material+24,8) && !memcmp(c->key+24,material+16,8));key_drop(&radio,&c,false);
 c=key_set(&radio,material,0,true,&error);assert(c && !error && c->cipher==4 && c->keylen==16 && (c->flags&1) && !memcmp(c->key,material,16));key_drop(&radio,&c,true);
 unsigned before=calls;radio.wpa.group_length=16;assert(!key_set(&radio,material,1,false,&error) && error==-EINVAL && calls==before);
 radio.wpa.group_length=32;assert(!key_set(&radio,material,4,false,&error) && error==-EINVAL && calls==before);
 radio.group_cipher=9;assert(!key_set(&radio,material,1,false,&error) && error==-EINVAL && calls==before);
 radio.group_cipher=2;no_memory=true;assert(!key_set(&radio,material,1,false,&error) && error==-ENOMEM && calls==before);no_memory=false;
 driver_error=-EIO;c=key_set(&radio,material,3,false,&error);assert(c && error==-EIO);key_drop(&radio,&c,false);
 assert(!allocated && !locked);puts("Station keys: CCMP and TKIP GTK, station Michael ordering, pairwise CCMP, bounds, failures and full key wiping passed");
}
'''
with tempfile.TemporaryDirectory(prefix='wifi-group-keys-') as tmp:
 p=Path(tmp);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
