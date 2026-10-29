#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
#define G 0x100000u
#define U 0x99c000u
#define P 0xf100000u
static uint32_t gcc[0x60000/4], uart[4096/4], pin[92][2];
static volatile bool renoir_bt_wanted=true;
static bool cancel_query;
static bool supplies,rcg_stuck,tx_stuck,no_reply;
static unsigned writes,txwords,rxwords,rxpos,waits;
static bool available;
static const uint8_t reply[]={4,14,18,1,0,0xfc,0,0x19,0,0x44,0x33,0x22,0x11,2,0,0x21,0,0x20,0x43,1,0x40};
static uint32_t rd(vm_offset_t p){
 if(p>=G && p<G+sizeof(gcc))return gcc[(p-G)/4];
 if(p>=U && p<U+sizeof(uart)){
  unsigned off=p-U;
  if(off==0x804)return available?(1u<<31|1u<<28|6):0;
  if(off==0x780){
   uint32_t v=0;rxwords++;
   for(unsigned i=0;i<4;i++){if(rxpos<sizeof(reply))v|=(uint32_t)reply[rxpos]<<(8*i);rxpos++;}
   if(rxpos>=sizeof(reply))available=false;
   return v;
  }
  return uart[off/4];
 }
 assert(p>=P && p<P+sizeof(pin)/sizeof(pin[0])*4096);
 unsigned n=(p-P)/4096,off=(p-P)%4096;assert(off==0 || off==4);return pin[n][off/4];
}
static void wr(vm_offset_t p,uint32_t value){
 writes++;
 if(p>=G && p<G+sizeof(gcc)){
  unsigned off=p-G;assert(off>=0x17860 && off<=0x17870);
  gcc[off/4]=(off==0x17860 && !rcg_stuck)?value&~1u:value;return;
 }
 if(p>=U && p<U+sizeof(uart)){
  unsigned off=p-U;
  if(off==0x630){assert(value==1u<<27);uart[0x40/4]|=0x1000;return;}
  if(off==0x600){uart[0x40/4]|=1;return;}
  if(off==0x604){uart[0x40/4]&=~1u;uart[0x610/4]|=1u<<5;return;}
  if(off==0x634){uart[0x40/4]&=~0x1000u;return;}
  if(off==0x618){uart[0x610/4]&=~value;return;}
  if(off==0x648){uart[0x640/4]&=~value;return;}
  if(off==0x700){
   assert(value==(txwords?0x19:0x01fc0001));txwords++;
   if(txwords==2 && !tx_stuck){uart[0x610/4]|=1;uart[0x40/4]&=~1u;available=!no_reply;}
   return;
  }
  uart[off/4]=value;return;
 }
 assert(p>=P && p<P+92*4096);
 unsigned n=(p-P)/4096,off=(p-P)%4096;
 assert((n==65 && (off==0 || off==4)) || (n>=68 && n<=71 && off==0));pin[n][off/4]=value;
}
static void sleep_us(uint32_t us){assert(us==10 || us==50);waits++;}
static void sleep_ms(uint32_t ms){assert(ms==1 || ms==50);waits++;if(cancel_query && ms==1)renoir_bt_wanted=false;}
static bool renoir_rpmh_read(const char *name,uint32_t off,uint32_t *v){
 assert(off==0 || off==4);unsigned mv=0;
 if(!strcmp(name,"smpb10"))mv=1800;else if(!strcmp(name,"ldoc11"))mv=2800;
 else if(!strcmp(name,"smpc2"))mv=952;else if(!strcmp(name,"smpb11"))mv=1880;
 else if(!strcmp(name,"smpb12"))mv=1350;else assert(0);
 *v=off?1:mv;return supplies;
}
#include "../../xnu/files/bsd/dev/renoir_bt_query.h"
static void fresh(void){
 memset(gcc,0,sizeof(gcc));memset(uart,0,sizeof(uart));memset(pin,0,sizeof(pin));
 gcc[0]=0x80000000;gcc[0x17864/4]=0x100000;gcc[0x17868/4]=27;gcc[0x1786c/4]=42;gcc[0x17870/4]=51;
 uart[0x68/4]=0x204;uart[0xe24/4]=0x20102864;uart[0xe28/4]=0x20204800;uart[0x48/4]=0x11;
 pin[65][0]=1;for(unsigned i=68;i<=71;i++)pin[i][0]=i==70?3:1;
 pin[64][0]=0x3c3;pin[64][1]=3;
 renoir_bt_wanted=true;cancel_query=false;supplies=true;rcg_stuck=tx_stuck=no_reply=available=false;writes=txwords=rxwords=rxpos=waits=0;
}
static void restored(void){
 assert(gcc[0x17864/4]==0x100000 && gcc[0x17868/4]==27 && gcc[0x1786c/4]==42 && gcc[0x17870/4]==51);
 assert(pin[65][0]==1 && pin[65][1]==0);
 for(unsigned i=68;i<=71;i++)assert(pin[i][0]==(i==70?3u:1u));
 assert(pin[64][0]==0x3c3 && pin[64][1]==3);
 assert(uart[0x48/4]==0x11 && uart[0x4c/4]==0 && uart[0x40/4]==0);
 assert(uart[0x258/4]==0 && uart[0x614/4]==0 && uart[0x644/4]==0);
}
int main(void){
 fresh();supplies=false;renoir_bluetooth_query(G,P,U,0x30000000);assert(!writes);
 fresh();renoir_bluetooth_query(G,P,U,0);assert(!writes);
 fresh();gcc[0]=0;renoir_bluetooth_query(G,P,U,0x30000000);assert(!writes);
 fresh();uart[0x40/4]=1;renoir_bluetooth_query(G,P,U,0x30000000);assert(!writes);
 fresh();pin[65][1]=1;renoir_bluetooth_query(G,P,U,0x30000000);assert(!writes);
 fresh();renoir_bluetooth_query(G,P,U,0x30000000);assert(txwords==2 && rxwords==6);restored();
 fresh();rcg_stuck=true;renoir_bluetooth_query(G,P,U,0x30000000);assert(!txwords && waits==2000);restored();
 fresh();uart[0xe24/4]=0;renoir_bluetooth_query(G,P,U,0x30000000);assert(!txwords);restored();
 fresh();no_reply=true;renoir_bluetooth_query(G,P,U,0x30000000);assert(txwords==2 && waits==5001);restored();
 fresh();tx_stuck=true;renoir_bluetooth_query(G,P,U,0x30000000);assert(txwords==2);restored();
 fresh();no_reply=true;cancel_query=true;renoir_bluetooth_query(G,P,U,0x30000000);assert(waits==2);restored();
 puts("QCA transaction: supply/ownership gates, ROM reply, timeouts and full temporary-state rollback passed");
}
