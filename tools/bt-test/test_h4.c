#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../../xnu/files/bsd/dev/renoir_bt_h4.h"
struct wire { unsigned count; uint16_t op; bool fail; };
static bool send_cmd(void *ctx,const uint8_t *b,size_t n) {
 struct wire *w=ctx;assert(b[0]==1);assert((n==4 && b[3]==0) || (n==5 && b[1]==0 && b[2]==0xfc && b[3]==1 && (b[4]==0x19 || b[4]==0x23)));w->op=rbt_le16(b+1);w->count++;return !w->fail;
}
static const uint8_t reset[]={4,14,4,1,3,12,0};
static const uint8_t version[]={4,14,12,1,1,16,0,9,0x34,0x12,9,29,0,0x78,0x56};
static const uint8_t address[]={4,14,10,1,9,16,0,6,5,4,3,2,0x02};
static void feed(struct renoir_bt_probe *p,const uint8_t *b,size_t n,unsigned chunk) {
 while(n){size_t z=n<chunk?n:chunk;rbt_feed(p,b,z);b+=z;n-=z;}
}
static struct renoir_bt_probe fresh(struct wire *w) {
 *w=(struct wire){0};struct renoir_bt_probe p={0};p.send=send_cmd;p.context=w;assert(rbt_start(&p));assert(w->op==0xc03);return p;
}
int main(void) {
 for(unsigned chunk=1;chunk<20;chunk++) {
  struct wire w;struct renoir_bt_probe p=fresh(&w);assert(!rbt_start(&p));
  /* Skip an unrelated completion and an ACL payload containing fake events. */
  uint8_t other[]={4,14,4,1,0,0,0,2,1,0,7,0,4,14,4,1,3,12,0};
  feed(&p,other,sizeof(other),chunk);assert(w.count==1 && p.state==RBT_RESET);
  feed(&p,reset,sizeof(reset),chunk);assert(p.state==RBT_VERSION && w.op==0x1001);
  feed(&p,version,sizeof(version),chunk);assert(p.state==RBT_ADDRESS && w.op==0x1009);
  feed(&p,address,sizeof(address),chunk);assert(p.state==RBT_DONE && w.count==3);
  assert(p.manufacturer==29 && p.revision==0x1234 && p.subversion==0x5678);
  assert(p.address[0]==6 && p.address[5]==2);
 }
 struct wire w;struct renoir_bt_probe p=fresh(&w);
 uint8_t error[]={4,15,4,0x0c,1,3,12};rbt_feed(&p,error,sizeof(error));assert(p.state==RBT_FAILED && p.status==12);
 p=fresh(&w);uint8_t no_credit[]={4,14,4,0,3,12,0};rbt_feed(&p,no_credit,sizeof(no_credit));assert(p.state==RBT_FAILED && w.count==1);
 p=fresh(&w);uint8_t bad_length[]={4,14,5,1,3,12,0,0};rbt_feed(&p,bad_length,sizeof(bad_length));assert(p.state==RBT_FAILED);
 p=fresh(&w);w.fail=true;rbt_feed(&p,reset,sizeof(reset));assert(p.state==RBT_FAILED);
 p=fresh(&w);rbt_feed(&p,reset,sizeof(reset));rbt_feed(&p,version,sizeof(version));
 uint8_t zero[sizeof(address)];memcpy(zero,address,sizeof(zero));memset(zero+7,0,6);rbt_feed(&p,zero,sizeof(zero));assert(p.state==RBT_FAILED);
 /* Largest ACL payload must be skipped rather than parsed as event bytes. */
 p=fresh(&w);uint8_t hdr[]={2,1,0,255,255};rbt_feed(&p,hdr,sizeof(hdr));
 for(unsigned i=0;i<65535;i++){uint8_t v=4;rbt_feed(&p,&v,1);}assert(p.state==RBT_RESET && w.count==1);
 rbt_feed(&p,reset,sizeof(reset));assert(p.state==RBT_VERSION);
 /* No partial event may advance the probe. */
 for(unsigned n=0;n<sizeof(reset);n++){p=fresh(&w);rbt_feed(&p,reset,n);assert(p.state==RBT_RESET);}
 /* Qualcomm ROM identity reply, fragmented at every byte. */
 p=(struct renoir_bt_probe){0};w=(struct wire){0};p.send=send_cmd;p.context=&w;
 assert(rbt_start_qca(&p));assert(w.op==0xfc00);
 uint8_t rom[]={4,14,18,1,0,0xfc,0,0x19,0,0x44,0x33,0x22,0x11,2,0,0x21,0,0x20,0x43,1,0x40};
 feed(&p,rom,sizeof(rom),1);assert(p.state==RBT_ROM_DONE);
 assert(p.product_id==0x11223344 && p.rom_version==0x21 && p.soc_id==0x40014320);
 assert(p.patch_version==2 && w.count==1);
 p=(struct renoir_bt_probe){0};p.send=send_cmd;p.context=&w;assert(rbt_start_qca(&p));
 rom[8]=0xa5;feed(&p,rom,sizeof(rom),1);assert(p.state==RBT_ROM_DONE);
 p=(struct renoir_bt_probe){0};p.send=send_cmd;p.context=&w;assert(rbt_start_qca(&p));
 rom[7]=1;feed(&p,rom,sizeof(rom),1);assert(p.state==RBT_FAILED);
 /* Exact non-personal identity reply captured from the physical Renoir.
  * Initial power-on NUL is noise; 0x0c after the EDL header is payload length. */
 const uint8_t captured[]={0,4,14,18,1,0,0xfc,0,0x19,0x0c,0x13,0,0,0,0xf3,0x17,0,2,0,2,0x0c,0x40};
 for(unsigned chunk=1;chunk<=sizeof(captured);chunk++){
  p=(struct renoir_bt_probe){0};p.send=send_cmd;p.context=&w;assert(rbt_start_qca(&p));
  feed(&p,captured,sizeof(captured),chunk);assert(p.state==RBT_ROM_DONE);
  assert(p.product_id==0x13 && p.soc_id==0x400c0200 && p.rom_version==0x200 && p.patch_version==0x17f3);
 }
 p=(struct renoir_bt_probe){0};p.send=send_cmd;p.context=&w;assert(rbt_start_qca(&p));
 feed(&p,captured,sizeof(captured),1);assert(!rbt_start_board(&p));
 p.state=RBT_TLV_DONE;assert(rbt_start_board(&p));assert(!rbt_start_board(&p));
 const uint8_t board[]={4,14,8,1,0,0xfc,0,0x23,2,0,0x8e};
 feed(&p,captured,sizeof(captured),1);assert(p.state==RBT_QCA_BOARD);
 feed(&p,board,sizeof(board),1);assert(p.state==RBT_BOARD_DONE && p.board_id==0x8e);
 puts("H4 probe: fragmentation, framing, identity, flow control and failure tests passed");
}
