#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../../xnu/files/bsd/dev/renoir_bt_firmware.h"
static uint8_t patch[600],nvm[256];
static size_t position,total;
static unsigned sends,pauses,mode;
static bool pending,alive,fail_send,silent,bad_ack,cancel;
static const uint8_t *expected;
static bool send_cmd(void *ctx,const uint8_t *b,size_t n){
 (void)ctx;assert(n>=7 && n<=249 && b[0]==1 && b[1]==0 && b[2]==0xfc && b[3]==n-4 && b[4]==0x1e && b[5]==n-6);
 assert(position+n-6<=total);assert(!memcmp(b+6,expected+position,n-6));position+=n-6;sends++;
 pending=(mode==0 || position==total);return !fail_send;
}
static bool running(void *ctx){(void)ctx;return alive;}
static int receive(void *ctx,uint8_t *b,size_t capacity){
 (void)ctx;assert(capacity>=8);
 if(!pending || silent)return 0;
 uint8_t ack[]={4,14,5,1,0,0xfc,0,0x1e};
 if(bad_ack)ack[6]=1;
 memcpy(b,ack,sizeof(ack));pending=false;return sizeof(ack);
}
static void pause_ms(void *ctx,unsigned ms){(void)ctx;assert(ms==1);pauses++;if(cancel)alive=false;}
static void put16(uint8_t *b,unsigned v){b[0]=v;b[1]=v>>8;}
static void put32(uint8_t *b,uint32_t v){put16(b,v);put16(b+2,v>>16);}
static void fresh(struct renoir_bt_probe *p,unsigned m){
 memset(p,0,sizeof(*p));p->state=RBT_ROM_DONE;p->soc_id=0x400c0200;p->product_id=0x13;p->rom_version=0x200;p->credits=1;p->send=send_cmd;
 memset(patch,0,sizeof(patch));put32(patch,1u|((sizeof(patch)-4)<<8));put32(patch+4,500);put32(patch+8,450);
 put16(patch+16,0x13);put16(patch+18,0x200);patch[14]=m;
 for(unsigned i=28;i<sizeof(patch);i++)patch[i]=(uint8_t)i;
 position=sends=pauses=0;total=sizeof(patch);mode=m;alive=true;pending=fail_send=silent=bad_ack=cancel=false;expected=patch;
}
static size_t tag(size_t off,unsigned id,unsigned len){put16(nvm+off,id);put16(nvm+off+2,len);return off+12+len;}
int main(void){
 struct renoir_bt_probe p;struct rbf_io io={running,receive,pause_ms,NULL};unsigned m;
 fresh(&p,3);assert(rbf_patch(patch,sizeof(patch),0x13,0x200,&m) && m==3);
 for(size_t n=0;n<sizeof(patch);n++)assert(!rbf_patch(patch,n,0x13,0x200,&m));
 assert(!rbf_patch(patch,sizeof(patch),0x14,0x200,&m));assert(!rbf_patch(patch,sizeof(patch),0x13,0x201,&m));
 assert(rbf_transfer(&p,&io,patch,sizeof(patch),3));assert(position==sizeof(patch) && sends==3 && p.state==RBT_TLV_DONE);
 fresh(&p,0);assert(rbf_transfer(&p,&io,patch,sizeof(patch),0) && sends==3);
 fresh(&p,3);silent=true;assert(!rbf_transfer(&p,&io,patch,sizeof(patch),3) && pauses==5002);
 fresh(&p,3);cancel=true;assert(!rbf_transfer(&p,&io,patch,sizeof(patch),3) && sends==1);
 fresh(&p,0);bad_ack=true;assert(!rbf_transfer(&p,&io,patch,sizeof(patch),0) && sends==1);
 fresh(&p,3);fail_send=true;assert(!rbf_transfer(&p,&io,patch,sizeof(patch),3));
 memset(nvm,0,sizeof(nvm));size_t n=tag(4,2,6);n=tag(n,17,3);n=tag(n,27,1);put32(nvm,2u|((n-4)<<8));assert(rbf_nvm_valid(nvm,n));
 uint8_t address[]={6,5,4,3,2,2};assert(rbf_nvm_prepare(nvm,n,address,0,false));assert(!memcmp(nvm+16,address,6));
 for(size_t z=0;z<n;z++)assert(!rbf_nvm_valid(nvm,z));
 fresh(&p,0);total=n;expected=nvm;
 assert(!rbf_transfer(&p,&io,nvm,n,0) && !sends); /* No NVM before checked board selection. */
 p.state=RBT_BOARD_DONE;assert(rbf_transfer(&p,&io,nvm,n,0) && sends==1);
 uint8_t before[256];memcpy(before,nvm,sizeof(nvm));uint8_t zero[6]={0};assert(!rbf_nvm_prepare(nvm,n,zero,0,false));assert(!memcmp(before,nvm,sizeof(nvm)));
 put16(nvm+4+18+2,0xffff);assert(!rbf_nvm_valid(nvm,n));
 puts("QCA firmware: TLV bounds/identity, ACK modes, cancellation, timeout and transactional NVM preparation passed");
}
