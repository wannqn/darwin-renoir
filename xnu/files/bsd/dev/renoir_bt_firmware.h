/* Bounded QCA TLV validation/preparation. Never write the source firmware blob.
 * Patch bytes are sent unchanged; NVM edits must use a private RAM copy.
 */
#ifndef RENOIR_BT_FIRMWARE_H
#define RENOIR_BT_FIRMWARE_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "renoir_bt_h4.h"
static inline uint16_t rbf_u16(const uint8_t *b){return b[0]|(uint16_t)b[1]<<8;}
static inline uint32_t rbf_u32(const uint8_t *b){return rbf_u16(b)|(uint32_t)rbf_u16(b+2)<<16;}
static inline bool rbf_tlv(const uint8_t *b,size_t n,unsigned type)
{ return b && n>=4 && (rbf_u32(b)&255)==type && (rbf_u32(b)>>8)==n-4; }
static inline bool rbf_patch(const uint8_t *b,size_t n,uint32_t product,uint16_t rom,unsigned *mode)
{
 if(!mode || n<28 || !rbf_tlv(b,n,1) || !product || !rom || product>65535 || rbf_u16(b+16)!=product || rbf_u16(b+18)!=rom)return false;
 if(!rbf_u32(b+4) || !rbf_u32(b+8) || rbf_u32(b+4)>n-4 || rbf_u32(b+8)>rbf_u32(b+4) || rbf_u32(b+8)>n-28)return false;
 /* Initial WCN6855 path supports per-segment replies or last-reply-only. */
 if(b[14]!=0 && b[14]!=3)return false;
 *mode=b[14];return true;
}
static inline bool rbf_nvm_valid(const uint8_t *b,size_t n)
{
 if(!rbf_tlv(b,n,2))return false;
 unsigned present=0;
 for(size_t off=4;off<n;){
  if(n-off<12)return false;
  unsigned tag=rbf_u16(b+off),len=rbf_u16(b+off+2);
  if(len>n-off-12)return false;
  unsigned bit=tag==2?1:tag==17?2:tag==27?4:0;
  if(bit){
   if(present&bit)return false;
   if((tag==2 && len!=6) || (tag==17 && len<3) || (tag==27 && len<1))return false;
   present|=bit;
  }
  off+=12+len;
 }
 return present==7;
}
static inline bool rbf_nvm_prepare(uint8_t *b,size_t n,const uint8_t address[6],uint8_t baud,bool ibs)
{
 if(!address || !rbf_nvm_valid(b,n) || baud>0x12)return false;
 uint8_t any=0,all=255;
 for(unsigned i=0;i<6;i++){any|=address[i];all&=address[i];}
 /* Public/locally administered unicast, HCI little-endian order. */
 if(!any || all==255 || (address[5]&1))return false;
 for(size_t off=4;off<n;){
  unsigned tag=rbf_u16(b+off),len=rbf_u16(b+off+2);uint8_t *v=b+off+12;
  if(tag==2)for(unsigned i=0;i<6;i++)v[i]=address[i];
  if(tag==17){v[0]=ibs?v[0]|0x80:v[0]&~0x80;v[1]=baud;}
  if(tag==27)v[0]=ibs?v[0]|1:v[0]&~1;
  off+=12+len;
 }
 return true;
}
struct rbf_io {
 bool (*running)(void *);
 int (*receive)(void *,uint8_t *,size_t);
 void (*pause_ms)(void *,unsigned);
 void *context;
};
static inline bool rbf_receive(struct renoir_bt_probe *p,const struct rbf_io *io)
{
 uint8_t b[256];int n=io->receive(io->context,b,sizeof(b));
 if(n<0 || n>(int)sizeof(b)){rbt_fail(p,0xf9);return false;}
 if(n)rbt_feed(p,b,(size_t)n);
 return p->state!=RBT_FAILED;
}
static inline bool rbf_transfer(struct renoir_bt_probe *p,const struct rbf_io *io,
 const uint8_t *data,size_t n,unsigned mode)
{
 if(!p || !io || !io->running || !io->receive || !io->pause_ms || !data || n<4 || !p->soc_id)return false;
 if(data[0]==1){
  if(p->state!=RBT_ROM_DONE && p->state!=RBT_BOARD_DONE && p->state!=RBT_TLV_DONE)return false;
  unsigned actual;
  if(!rbf_patch(data,n,p->product_id,p->rom_version,&actual) || mode!=actual)return false;
 }else if(data[0]==2){
  if(mode || p->state!=RBT_BOARD_DONE || !rbf_nvm_valid(data,n))return false;
 }else return false;
 for(size_t off=0;off<n;){
  if(!io->running(io->context)){rbt_fail(p,0xfb);return false;}
  size_t count=n-off;if(count>243)count=243;
  bool wait=mode==0 || count==n-off;
  if(!rbt_tlv_segment(p,data+off,count,wait))return false;
  if(wait){
   unsigned ms;
   for(ms=0;ms<5000 && p->state==RBT_TLV_WAIT;ms++){
    if(!io->running(io->context)){rbt_fail(p,0xfb);return false;}
    if(!rbf_receive(p,io))return false;
    if(p->state==RBT_TLV_WAIT)io->pause_ms(io->context,1);
   }
   if(p->state!=RBT_TLV_DONE || !p->credits){rbt_fail(p,0xfa);return false;}
  }else if(!rbf_receive(p,io))return false;
  off+=count;
  if(off<n)io->pause_ms(io->context,1);
 }
 return p->state==RBT_TLV_DONE;
}
#endif
