/* GENI UART FIFO transport. Register facts: Qualcomm GENI / Linux UART driver.
 * The serialized owner must establish clocks, power, pinmux and UART firmware.
 * No DMA, interrupt registration, clock/power votes, or unsolicited reset here.
 */
#ifndef RENOIR_BT_GENI_H
#define RENOIR_BT_GENI_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
struct rbt_geni {
 uint32_t (*read)(void *,unsigned);
 void (*write)(void *,unsigned,uint32_t);
 void (*delay_us)(void *,unsigned);
 void *ctx;
 unsigned depth, rx_depth;
 bool ready;
};
static inline bool rbt_geni_wait(struct rbt_geni *u,unsigned reg,uint32_t mask,uint32_t value)
{
 for(unsigned i=0;i<1000;i++) {
  if((u->read(u->ctx,reg)&mask)==value)return true;
  u->delay_us(u->ctx,50);
 }
 return false;
}
static inline bool rbt_geni_configure(struct rbt_geni *u,uint32_t clock_hz,unsigned selection,unsigned sampling,unsigned baud)
{
 u->ready=false;
 if(!u->read || !u->write || !u->delay_us || selection>7 ||
    (sampling!=16 && sampling!=32) || baud<9600 || baud>4000000)return false;
 uint64_t target=(uint64_t)baud*sampling;
 uint32_t divider=((uint64_t)clock_hz+target/2)/target;
 if(!divider || divider>4095)return false;
 uint64_t actual=(uint64_t)clock_hz/divider;
 uint64_t error=actual>target?actual-target:target-actual;
 if(error*100>target)return false; /* no more than one percent baud error */
 if(((u->read(u->ctx,0x68)>>8)&255)!=2 || (u->read(u->ctx,0x64)&1))return false;
 u->depth=(u->read(u->ctx,0xe24)>>16)&63;
 unsigned width=(u->read(u->ctx,0xe24)>>24)&63;
 uint32_t rx_hw=u->read(u->ctx,0xe28);
 u->rx_depth=(rx_hw>>16)&63;
 if(u->depth<4 || width!=32 || u->rx_depth<4 || ((rx_hw>>24)&63)!=32)return false;
 /* Do not take over a sequencer with an existing user, or discard its data. */
 if((u->read(u->ctx,0x40)&0x1001) || u->read(u->ctx,0x800) ||
    (u->read(u->ctx,0x804)&0x1ffffff))return false;
 #define BW(reg,val) u->write(u->ctx,reg,val)
 BW(0xe18,0);BW(0x258,0); /* disable GSI events and select FIFO */
 BW(0xe1c,0xf);BW(0x28,u->read(u->ctx,0x28)|0x7f);
 BW(0x24,0x7f);BW(0x20,1);
 BW(0x260,0x4380e);BW(0x264,0xc3e0e);
 BW(0x284,0x4380e);BW(0x288,0xc3e0e);BW(0x254,0);
 BW(0x22c,0);BW(0x25c,0);BW(0x280,0); /* 8N1, CTS flow control */
 BW(0x268,8);BW(0x28c,8);BW(0x26c,0);BW(0x2a4,0);BW(0x2a8,0);
 BW(0x294,160);BW(0x2ac,0);BW(0x7c,selection);
 BW(0x48,divider<<4|1);BW(0x4c,divider<<4|1);
 BW(0x80c,0);BW(0x810,2);BW(0x814,u->rx_depth-2);
 BW(0x618,0xffffffff);BW(0x648,0xffffffff);
 BW(0x614,1);BW(0x644,(1u<<26)|(1u<<27));
 BW(0x630,1u<<27); /* UART_START_READ on secondary sequencer */
 #undef BW
 u->ready=true;return true;
}
static inline bool rbt_geni_tx(struct rbt_geni *u,const uint8_t *data,size_t size)
{
 if(!u->ready || !size || size>4*u->depth || !data)return false;
 if((u->read(u->ctx,0x40)&1) || u->read(u->ctx,0x800))return false;
 u->write(u->ctx,0x618,1);
 u->write(u->ctx,0x270,(uint32_t)size);
 u->write(u->ctx,0x600,1u<<27);
 for(size_t i=0;i<size;i+=4){
  uint32_t word=0;
  for(unsigned j=0;j<4 && i+j<size;j++)word|=(uint32_t)data[i+j]<<(8*j);
  u->write(u->ctx,0x700,word);
 }
 if(rbt_geni_wait(u,0x610,1,1)){u->write(u->ctx,0x618,1);return true;}
 u->write(u->ctx,0x604,2); /* Abort a timed-out transfer; owner must reset state. */
 (void)rbt_geni_wait(u,0x610,1u<<5,1u<<5);
 u->write(u->ctx,0x618,1u<<5);u->ready=false;return false;
}
/* Preserve one H4 byte stream across bounded hardware FIFO transfers. */
static inline bool rbt_geni_stream_tx(struct rbt_geni *u,const uint8_t *data,size_t size)
{
 if(!u->ready || !data || !size || size>65540 || !u->depth)return false;
 while(size){
  size_t count=size;if(count>4*u->depth)count=4*u->depth;
  if(!rbt_geni_tx(u,data,count))return false;
  data+=count;size-=count;
 }
 return true;
}
/* One FIFO snapshot, bounded by advertised hardware capacity. */
static inline int rbt_geni_rx(struct rbt_geni *u,uint8_t *out,size_t capacity)
{
 if(!u->ready || !out)return -1;
 uint32_t status=u->read(u->ctx,0x804);unsigned words=status&0x1ffffff;
 unsigned last=(status>>28)&7;
 if(words>u->rx_depth || ((status>>31) && last>4)){u->ready=false;return -1;}
 size_t bytes=words*4;
 if(words && (status>>31) && last)bytes-=4-last;
 if(bytes>capacity)return -1; /* Leave the FIFO untouched for the owner to retry. */
 size_t count=0;
 for(unsigned i=0;i<words;i++) {
  uint32_t word=u->read(u->ctx,0x780);
  for(unsigned j=0;j<4 && count<bytes;j++)out[count++]=(uint8_t)(word>>(8*j));
 }
 u->write(u->ctx,0x648,(1u<<26)|(1u<<27));
 return (int)count;
}
#endif
