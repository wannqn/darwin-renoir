#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../../xnu/files/bsd/dev/renoir_bt_geni.h"
struct model {uint32_t regs[1024];unsigned writes,delays,pops;bool stuck;};
static uint32_t read_reg(void *ctx,unsigned off){
 struct model *m=ctx;assert(off<4096 && !(off&3));
 if(off==0x610)return m->stuck?0:1;
 if(off==0x780){m->pops++;return 0x04030201;}
 return m->regs[off/4];
}
static void write_reg(void *ctx,unsigned off,uint32_t value){
 struct model *m=ctx;assert(off<4096 && !(off&3));m->regs[off/4]=value;m->writes++;
}
static void delay(void *ctx,unsigned us){struct model *m=ctx;assert(us==50);m->delays++;}
static struct rbt_geni fresh(struct model *m){
 memset(m,0,sizeof(*m));m->regs[0x68/4]=2<<8;m->regs[0xe24/4]=(32u<<24)|(16<<16);m->regs[0xe28/4]=m->regs[0xe24/4];
 return (struct rbt_geni){read_reg,write_reg,delay,m,0,0,false};
}
int main(void){
 struct model m;struct rbt_geni u=fresh(&m);
 assert(!rbt_geni_configure(&u,19200000,0,16,115200)&&!m.writes);
 assert(!rbt_geni_configure(&u,7372800,8,16,115200)&&!m.writes);
 m.regs[0x40/4]=0x1000;assert(!rbt_geni_configure(&u,7372800,0,16,115200)&&!m.writes);
 u=fresh(&m);m.regs[0x68/4]=1<<8;assert(!rbt_geni_configure(&u,7372800,0,16,115200)&&!m.writes);
 u=fresh(&m);assert(rbt_geni_configure(&u,7372800,0,16,115200));assert(u.ready);
 assert(m.regs[0x48/4]==65 && m.regs[0x4c/4]==65);
 assert(m.regs[0x260/4]==0x4380e && m.regs[0x264/4]==0xc3e0e);
 uint8_t cmd[]={1,0,0xfc,1,0x19};assert(rbt_geni_tx(&u,cmd,sizeof(cmd)));
 assert(m.regs[0x270/4]==5 && m.regs[0x700/4]==0x19);
 assert(!rbt_geni_tx(&u,cmd,65));
 m.regs[0x804/4]=1u<<31|1u<<28|2;uint8_t b[64];
 assert(rbt_geni_rx(&u,b,4)==-1 && !m.pops);
 assert(rbt_geni_rx(&u,b,sizeof(b))==5 && m.pops==2);
 assert(b[0]==1 && b[3]==4 && b[4]==1);
 m.regs[0x804/4]=17;assert(rbt_geni_rx(&u,b,sizeof(b))==-1 && !u.ready);
 u=fresh(&m);assert(rbt_geni_configure(&u,7372800,0,32,115200));
 m.stuck=true;assert(!rbt_geni_tx(&u,cmd,sizeof(cmd)) && !u.ready);
 assert(m.delays==2000 && m.regs[0x604/4]==2);
 puts("GENI FIFO: configuration gates, byte packing, partial RX and bounded timeout tests passed");
}
