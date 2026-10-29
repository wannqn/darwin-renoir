/* Renoir Bluetooth H4 bring-up core. No MMIO, firmware download or automatic activation.
 * Wire format: Bluetooth Core HCI UART / HCI Command Complete events.
 * Call from one serialized UART worker; send must not reenter rbt_feed.
 * The caller supplies transport, IBS handling and deadlines.
 */
#ifndef RENOIR_BT_H4_H
#define RENOIR_BT_H4_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
struct renoir_bt_probe {
 uint8_t frame[258];
 uint32_t have, need, discard;
 uint8_t type, state, status, hci_version, lmp_version;
 uint16_t opcode, revision, manufacturer, subversion, board_id;
 uint8_t credits;
 uint32_t product_id, soc_id;
 uint16_t patch_version, rom_version;
 uint8_t address[6]; /* HCI order, least significant byte first */
 bool (*send)(void *, const uint8_t *, size_t);
 void *context;
};
enum { RBT_IDLE, RBT_RESET, RBT_VERSION, RBT_ADDRESS, RBT_DONE, RBT_FAILED, RBT_QCA_VERSION, RBT_ROM_DONE, RBT_QCA_BOARD, RBT_BOARD_DONE, RBT_TLV_STREAM, RBT_TLV_WAIT, RBT_TLV_DONE };
static inline void rbt_fail(struct renoir_bt_probe *p, uint8_t status)
{ p->state=RBT_FAILED; p->status=status; }
static inline bool rbt_command(struct renoir_bt_probe *p, uint8_t state, uint16_t opcode)
{
 uint8_t cmd[]={1,(uint8_t)opcode,(uint8_t)(opcode>>8),0};
 p->state=state; p->opcode=opcode;
 if (!p->send || !p->send(p->context,cmd,sizeof(cmd))) { rbt_fail(p,0xff); return false; }
 return true;
}
static inline bool rbt_start(struct renoir_bt_probe *p)
{
 /* A running or failed instance must be explicitly reinitialized by its owner. */
 if(p->state!=RBT_IDLE)return false;
 return rbt_command(p,RBT_RESET,0x0c03);
}
/* Qualcomm WCN3991-and-newer ROM query. No firmware is chosen or downloaded. */
static inline bool rbt_start_qca(struct renoir_bt_probe *p)
{
 const uint8_t cmd[]={1,0,0xfc,1,0x19};
 if(p->state!=RBT_IDLE)return false;
 p->state=RBT_QCA_VERSION;p->opcode=0xfc00;
 if(!p->send || !p->send(p->context,cmd,sizeof(cmd))){rbt_fail(p,0xff);return false;}
 return true;
}
/* QCA reference queries board ID after patch loading, never in bare ROM. */
static inline bool rbt_start_board(struct renoir_bt_probe *p)
{
 const uint8_t cmd[]={1,0,0xfc,1,0x23};
 if(p->state!=RBT_TLV_DONE || !p->credits)return false;
 p->state=RBT_QCA_BOARD;p->opcode=0xfc00;p->credits--;
 if(!p->send || !p->send(p->context,cmd,sizeof(cmd))){rbt_fail(p,0xff);return false;}
 return true;
}
static inline bool rbt_tlv_segment(struct renoir_bt_probe *p,const uint8_t *data,size_t n,bool wait)
{
 if(!data || !n || n>243 || (p->state!=RBT_ROM_DONE && p->state!=RBT_BOARD_DONE &&
    p->state!=RBT_TLV_STREAM && p->state!=RBT_TLV_DONE))return false;
 uint8_t cmd[249]={1,0,0xfc,(uint8_t)(n+2),0x1e,(uint8_t)n};
 for(size_t i=0;i<n;i++)cmd[6+i]=data[i];
 p->state=wait?RBT_TLV_WAIT:RBT_TLV_STREAM;p->opcode=0xfc00;
 if(!p->send || !p->send(p->context,cmd,n+6)){rbt_fail(p,0xff);return false;}
 return true;
}
static inline uint16_t rbt_le16(const uint8_t *b) { return b[0]|(uint16_t)b[1]<<8; }
static inline void rbt_event(struct renoir_bt_probe *p)
{
 const uint8_t *b=p->frame; uint8_t n=b[1];
 if(p->state==RBT_TLV_WAIT || p->state==RBT_TLV_STREAM){
  if(b[0]==0x0f && n==4 && rbt_le16(b+4)==0xfc00){if(b[2])rbt_fail(p,b[2]);return;}
  if(b[0]!=0x0e || n<3 || rbt_le16(b+3)!=0xfc00)return;
  if(n>=5 && (b[6]==0x19 || b[6]==0x23))return; /* Delayed identity response. */
  if(n!=5 || b[5]!=0 || b[6]!=0x1e || p->state==RBT_TLV_STREAM){rbt_fail(p,0xfd);return;}
  p->credits=b[2];p->state=RBT_TLV_DONE;return;
 }
 if(p->state==RBT_QCA_BOARD) {
  if(b[0]==0x0f && n==4 && rbt_le16(b+4)==0xfc00){if(b[2])rbt_fail(p,b[2]);return;}
  if(b[0]!=0x0e || n<3 || rbt_le16(b+3)!=0xfc00)return;
  if(n>=5 && b[6]==0x19)return; /* Ignore a late ROM-version completion. */
  if(n<8 || b[5]!=0 || b[6]!=0x23){rbt_fail(p,0xfd);return;}
  p->credits=b[2];p->board_id=(uint16_t)b[8]<<8|b[9];p->state=RBT_BOARD_DONE;return;
 }
 if(p->state==RBT_QCA_VERSION) {
  if(b[0]==0x0f && n==4 && rbt_le16(b+4)==0xfc00) {
   if(b[2])rbt_fail(p,b[2]);
   return;
  }
  if(b[0]!=0x0e || n<3 || rbt_le16(b+3)!=0xfc00)return;
  if(n!=18 || b[5]!=0 || b[6]!=0x19){rbt_fail(p,0xfd);return;}
  /* QCA skips the extra byte after the EDL header; it is not HCI status. */
  p->product_id=rbt_le16(b+8)|(uint32_t)rbt_le16(b+10)<<16;
  p->patch_version=rbt_le16(b+12);p->rom_version=rbt_le16(b+14);
  p->soc_id=rbt_le16(b+16)|(uint32_t)rbt_le16(b+18)<<16;
  if(!p->rom_version || !p->soc_id){rbt_fail(p,0xfd);return;}
  p->credits=b[2];p->state=RBT_ROM_DONE;return;
 }
 if(p->state<RBT_RESET || p->state>RBT_ADDRESS)return;
 if(b[0]==0x0f && n==4 && rbt_le16(b+4)==p->opcode) {
  if(b[2])rbt_fail(p,b[2]); /* success means wait for Command Complete */
  return;
 }
 if(b[0]!=0x0e || n<4 || rbt_le16(b+3)!=p->opcode)return;
 if(b[5]){rbt_fail(p,b[5]);return;}
 /* No next command may be sent without a controller command credit. */
 if(!b[2]){rbt_fail(p,0xfe);return;}
 if(p->state==RBT_RESET) {
  if(n!=4){rbt_fail(p,0xfd);return;}
  rbt_command(p,RBT_VERSION,0x1001);
 } else if(p->state==RBT_VERSION) {
  if(n!=12){rbt_fail(p,0xfd);return;}
  p->hci_version=b[6];p->revision=rbt_le16(b+7);p->lmp_version=b[9];
  p->manufacturer=rbt_le16(b+10);p->subversion=rbt_le16(b+12);
  rbt_command(p,RBT_ADDRESS,0x1009);
 } else {
  if(n!=10){rbt_fail(p,0xfd);return;}
  uint8_t any=0, all=0xff;
  for(unsigned i=0;i<6;i++){p->address[i]=b[6+i];any|=b[6+i];all&=b[6+i];}
  if(!any || all==0xff){rbt_fail(p,0xfc);return;}
  p->state=RBT_DONE;
 }
}
static inline void rbt_feed(struct renoir_bt_probe *p,const uint8_t *data,size_t length)
{
 for(size_t i=0;i<length;i++) {
  uint8_t v=data[i];
  if(p->discard){p->discard--;continue;}
  if(!p->type){
   if(v==4){p->type=v;p->need=2;p->have=0;}
   else if(v==2 || v==3 || v==5){p->type=v;p->need=v==3?3:4;p->have=0;}
   /* Unknown bytes (including QCA IBS) are not H4 packet starts here.
    * The UART owner must process IBS and provide its acknowledgements separately. */
   continue;
  }
  p->frame[p->have++]=v;
  if(p->have!=p->need)continue;
  if(p->type!=4){
   p->discard=p->type==3?p->frame[2]:rbt_le16(p->frame+2);
   if(p->type==5)p->discard&=0x3fff; /* ISO length has reserved upper bits */
   p->type=0;p->have=0;continue;
  }
  if(p->need==2 && p->frame[1]){p->need+=p->frame[1];continue;}
  /* The send callback queues output; the serialized owner feeds input later. */
  p->type=0;
  rbt_event(p);
  p->have=0;
 }
}
#endif
