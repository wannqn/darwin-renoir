/* Opt-in, reversible QCA ROM identification. No firmware download or iOS service.
 * Included after Renoir's RPMh helpers in redwood_wifi.c. Never alter WLAN_EN.
 */
#ifndef RENOIR_BT_QUERY_H
#define RENOIR_BT_QUERY_H
#include "renoir_bt_h4.h"
#include "renoir_bt_geni.h"
static uint32_t rbq_read(void *ctx,unsigned off){return rd((vm_offset_t)ctx+off);}
static void rbq_write(void *ctx,unsigned off,uint32_t v){wr((vm_offset_t)ctx+off,v);}
static void rbq_delay(void *ctx,unsigned us){(void)ctx;sleep_us(us);}
static bool rbq_send(void *ctx,const uint8_t *b,size_t n){return rbt_geni_tx(ctx,b,n);}
static bool rbq_rcg_update(vm_offset_t gcc)
{
 wr(gcc+0x17860,rd(gcc+0x17860)|1);
 for(unsigned i=0;i<1000;i++){
  if(!(rd(gcc+0x17860)&1))return true;
  sleep_us(10);
 }
 return false;
}
static void
renoir_bluetooth_query(vm_offset_t gcc,vm_offset_t pins,vm_offset_t uart,uint32_t version)
{
 /* These existing Wi-Fi votes cover the shared combo-radio rails. Read them
  * under the existing RPMh lock, but do not change a regulator vote here. */
 static const char *const rail[]={"smpb10","ldoc11","smpc2","smpb11","smpb12"};
 static const uint32_t minimum[]={1800,2800,950,1880,1350};
 for(unsigned i=0;i<5;i++){
  uint32_t mv,on;
  if(!renoir_rpmh_read(rail[i],0,&mv) || !renoir_rpmh_read(rail[i],4,&on) || !(on&1) || (mv&8191)<minimum[i]){
   printf("renoir-bt: controller query refused: existing %s supply vote not ready\n",rail[i]);return;
  }
 }
 if(version!=0x30000000 || (rd(gcc+0x17874)&1) || !(rd(gcc)&0x80000000u)){
  printf("renoir-bt: query refused: QUP %#x DFS %#x PLL0 mode %#x\n",version,rd(gcc+0x17874),rd(gcc));return;
 }
 if((rd(uart+0x40)&0x1001) || rd(uart+0x800) || (rd(uart+0x804)&0x1ffffff) || (rd(uart+0x258)&1)){
  printf("renoir-bt: query refused: UART sequencer/FIFO/DMA already in use\n");return;
 }
 vm_offset_t enable=pins+65*0x1000;
 uint32_t enable_cfg=rd(enable),enable_io=rd(enable+4);
 if(enable_io&3){printf("renoir-bt: query refused: BT_EN already active\n");return;}
 static const unsigned reg[]={0xe18,0x258,0xe1c,0x28,0x24,0x260,0x264,0x284,0x288,0x254,
  0x22c,0x25c,0x280,0x268,0x28c,0x26c,0x2a4,0x2a8,0x294,0x2ac,0x7c,0x48,0x4c,
  0x80c,0x810,0x814,0x614,0x644};
 uint32_t saved[sizeof(reg)/sizeof(reg[0])], pin_cfg[4], clock[4];
 for(unsigned i=0;i<sizeof(reg)/sizeof(reg[0]);i++)saved[i]=rd(uart+reg[i]);
 for(unsigned i=0;i<4;i++){pin_cfg[i]=rd(pins+(68+i)*0x1000);clock[i]=rd(gcc+0x17864+4*i);}
 bool uart_changed=false, pins_changed=false, enable_changed=false;
 /* S7's private RCG: 300 MHz GPLL0-even * 384/15625 = 7.3728 MHz.
  * Parent already locked. Do not vote, reprogram or stop the shared PLL. */
 wr(gcc+0x17868,(clock[1]&~0xffffu)|384);
 wr(gcc+0x1786c,(clock[2]&~0xffffu)|((~(15625u-384u))&0xffff));
 wr(gcc+0x17870,(clock[3]&~0xffffu)|((~15625u)&0xffff));
 wr(gcc+0x17864,(clock[0]&~0x371fu)|0x2601);
 if(!rbq_rcg_update(gcc)){printf("renoir-bt: UART baud-clock update timed out\n");goto cleanup;}
 if((rd(gcc+0x17864)&0x371f)!=0x2601){printf("renoir-bt: UART baud-clock readback mismatch\n");goto cleanup;}
 for(unsigned i=0;i<4;i++)wr(pins+(68+i)*0x1000,4|(i==1?1:i==2?3:0));
 pins_changed=true;
 struct rbt_geni transport={rbq_read,rbq_write,rbq_delay,(void*)uart,0,0,false};
 /* Mark before configuration, so even partial setup is rolled back. */
 uart_changed=true;
 if(!rbt_geni_configure(&transport,7372800,0,16,115200)){
  printf("renoir-bt: UART FIFO configuration refused\n");goto cleanup;
 }
 wr(enable+4,2);wr(enable,0x201);enable_changed=true;
 sleep_ms(50);
 printf("renoir-bt: BT_EN high; SW_CTRL %u CTS %u; querying ROM at 115200\n",
  rd(pins+91*0x1000+4)&1,rd(pins+68*0x1000+4)&1);
 struct renoir_bt_probe probe={0};probe.send=rbq_send;probe.context=&transport;
 unsigned received=0, captured=0;uint8_t trace[64];
 if(rbt_start_qca(&probe)){
  for(unsigned ms=0;ms<5000 && renoir_bt_wanted && probe.state==RBT_QCA_VERSION;ms++){
   uint8_t b[256];int n=rbt_geni_rx(&transport,b,sizeof(b));
   if(n<0){printf("renoir-bt: UART receive error\n");break;}
   if(n){
    for(int i=0;i<n && captured<sizeof(trace);i++)trace[captured++]=b[i];
    received+=(unsigned)n;rbt_feed(&probe,b,(size_t)n);
   }
   if(probe.state==RBT_QCA_VERSION)sleep_ms(1);
  }
 }
 printf("renoir-bt: ROM receive bytes (%u captured):",captured);
 for(unsigned i=0;i<captured;i++)printf(" %02x",trace[i]);
 printf("\n");
 if(probe.state==RBT_ROM_DONE){
  printf("renoir-bt: QCA ROM identity: product %#x SOC %#x ROM %#x patch %#x\n",
   probe.product_id,probe.soc_id,probe.rom_version,probe.patch_version);
 }else{
  printf("renoir-bt: ROM query incomplete: state %u error %#x bytes %u UART %#x IRQ %#x/%#x RX %#x CTS %u\n",
   probe.state,probe.status,received,rd(uart+0x40),rd(uart+0x610),rd(uart+0x640),rd(uart+0x804),rd(pins+68*0x1000+4)&1);
 }
cleanup:
 if(enable_changed){wr(enable+4,enable_io&2);wr(enable,enable_cfg);}
 if(uart_changed){
  /* Stop only sequencers started by this experiment; DMA was never enabled. */
  if(rd(uart+0x40)&1)wr(uart+0x604,2);
  if(rd(uart+0x40)&0x1000)wr(uart+0x634,2);
  for(unsigned i=0;i<1000 && (rd(uart+0x40)&0x1001);i++)sleep_us(10);
  printf("renoir-bt: UART stopped status %#x\n",rd(uart+0x40));
  wr(uart+0x618,0xffffffff);wr(uart+0x648,0xffffffff);
  for(unsigned i=0;i<sizeof(reg)/sizeof(reg[0]);i++)wr(uart+reg[i],saved[i]);
 }
 if(pins_changed)for(unsigned i=0;i<4;i++)wr(pins+(68+i)*0x1000,pin_cfg[i]);
 for(unsigned i=0;i<4;i++)wr(gcc+0x17864+4*i,clock[i]);
 bool restored=rbq_rcg_update(gcc);
 for(unsigned i=0;i<4;i++)if(rd(gcc+0x17864+4*i)!=clock[i])restored=false;
 printf("renoir-bt: query cleanup: RCG restored %u; BT_EN cfg %#x io %#x; WLAN_EN unchanged by probe\n",restored,rd(enable),rd(enable+4));
}
#endif
