/* Renoir-only, opt-in Bluetooth hardware survey. Included by redwood_wifi.c.
 * Shima GCC: UART SE15 is wrapper 0 SE7 (not wrapper 1). Mode 1 is read-only;
 * mode 2 temporarily votes only this UART clock. Mode 3 also configures the
 * UART/pins and temporarily enables BT_EN for a ROM query, restoring on exit.
 * No firmware download or publication of a fictitious HCI device.
 */
#ifndef RENOIR_BLUETOOTH_H
#define RENOIR_BLUETOOTH_H
static volatile bool renoir_bt_wanted, renoir_bt_running;
#include "renoir_bt_query.h"
static void
renoir_bluetooth_probe_run(unsigned mode)
{
 vm_offset_t gcc=ml_io_map(0x00100000,0x60000);
 vm_offset_t pins=ml_io_map(0x0f100000,0x100000);
 if(!gcc || !pins){printf("renoir-bt: register mapping failed\n");return;}
 uint32_t vote=rd(gcc+0x52008), status=rd(gcc+0x1785c);
 bool clock_added=false;
 if(mode>=2) {
  /* Wrapper clocks belong to other clients. Require their existing votes;
   * this experiment changes only S7 and never changes an RCG or shared rail. */
  if((vote&0x3c0)!=0x3c0){printf("renoir-bt: wrapper clocks not voted; refusing clock probe\n");return;}
  clock_added=!(vote&(1u<<17));
  if(clock_added)wr(gcc+0x52008,rd(gcc+0x52008)|(1u<<17));
  for(unsigned i=0;i<1000;i++) {
   status=rd(gcc+0x1785c);
   if(!(status&0x80000000u))break;
   sleep_us(10);
  }
  printf("renoir-bt: temporary S7 clock vote: added %u, votes %#x branch %#x\n",
   clock_added,rd(gcc+0x52008),status);
 }
 printf("renoir-bt: UART SE15/wrap0-S7: votes %#x branch %#x; mode %u\n",vote,status,mode);
 printf("renoir-bt: clock RCG cmd %#x cfg %#x DFS %#x\n",
  rd(gcc+0x17860),rd(gcc+0x17864),rd(gcc+0x17874));
 const unsigned gpio[]={64,65,68,69,70,71,91};
 for(unsigned i=0;i<sizeof(gpio)/sizeof(gpio[0]);i++) {
  vm_offset_t p=pins+0x1000*gpio[i];
  printf("renoir-bt: GPIO%u cfg %#x io %#x\n",gpio[i],rd(p),rd(p+4));
 }
 /* A powered-down serial engine may external-abort, rather than read as zero.
  * Never touch its aperture until both wrapper AHB paths and its clock are on. */
 uint32_t master=rd(gcc+0x17004), slave=rd(gcc+0x17008);
 bool ahb_master=!(master&0x80000000u) || (master&2);
 bool ahb_slave=!(slave&0x80000000u) || (slave&2);
 if((status&0x80000000u) || !ahb_master || !ahb_slave) {
  printf("renoir-bt: UART clock off: SE %#x M-AHB %#x S-AHB %#x; UART MMIO skipped\n",status,master,slave);
  goto restore;
 }
 vm_offset_t uart=ml_io_map(0x0099c000,0x4000);
 if(!uart){printf("renoir-bt: UART mapping failed\n");goto restore;}
 uint32_t rev=rd(uart+0x68), protocol=(rev>>8)&0xff;
 printf("renoir-bt: UART firmware %#x protocol %u (UART=2); FIFO disabled %#x\n",rev,protocol,rd(uart+0x64));
 if(protocol!=2){printf("renoir-bt: no UART firmware; no controller command sent\n");goto restore;}
 printf("renoir-bt: UART status %#x clock M %#x S %#x; hardware parameters %#x/%#x\n",
  rd(uart+0x40),rd(uart+0x48),rd(uart+0x4c),rd(uart+0xe24),rd(uart+0xe28));
 vm_offset_t wrapper=ml_io_map(0x009c0000,0x2000);
 if(wrapper)printf("renoir-bt: QUP wrapper hardware version %#x\n",rd(wrapper+4));
 if(mode==3 && wrapper)renoir_bluetooth_query(gcc,pins,uart,rd(wrapper+4));
 if(mode!=3)printf("renoir-bt: UART TX/RX FIFO status %#x/%#x; no data consumed\n",rd(uart+0x800),rd(uart+0x804));
restore:
 if(clock_added) {
  wr(gcc+0x52008,rd(gcc+0x52008)&~(1u<<17));
  for(unsigned i=0;i<1000 && !(rd(gcc+0x1785c)&0x80000000u);i++)sleep_us(10);
  printf("renoir-bt: removed temporary S7 clock vote; votes %#x branch %#x\n",rd(gcc+0x52008),rd(gcc+0x1785c));
 }
}
static void
renoir_bluetooth_worker(void *unused, wait_result_t result)
{
 (void)result;
 unsigned mode=(unsigned)(uintptr_t)unused;
 /* Let existing touchscreen/Wi-Fi clock initialization finish first. */
 if(mode>=2)for(unsigned i=0;i<300 && renoir_bt_wanted;i++)sleep_ms(100);
 if(!renoir_bt_wanted)goto finished;
 if(mode==3) {
  printf("renoir-bt: waiting up to 180 seconds for the temporary Wi-Fi supply prerequisite\n");
  for(unsigned i=0;i<180 && renoir_bt_wanted && !renoir_transport_ready;i++)sleep_ms(1000);
  if(!renoir_transport_ready){printf("renoir-bt: controller probe deferred: Wi-Fi transport not ready\n");goto finished;}
 }
 if(renoir_bt_wanted)renoir_bluetooth_probe_run(mode);
finished:
 renoir_bt_running=false;
 thread_terminate(current_thread());
}
static void
renoir_bluetooth_stop(void)
{
 renoir_bt_wanted=false;
 for(unsigned i=0;i<500 && renoir_bt_running;i++)sleep_ms(10);
 if(renoir_bt_running)printf("renoir-bt: probe has not finished cleanup before stop timeout\n");
}
static void
renoir_bluetooth_init(void)
{
 uint32_t mode=0;
 if(!PE_parse_boot_argn("bluetooth_probe",&mode,sizeof(mode)) || !mode)return;
 if((mode<1 || mode>3) || !redwood_board_is("renoir") || pe_arm_get_soc_base_phys()!=REDWOOD_SOC_BASE){
  printf("renoir-bt: refused: bluetooth_probe=1/2/3 requires physical renoir\n");return;
 }
 thread_t worker;
 renoir_bt_wanted=renoir_bt_running=true;
 if(kernel_thread_start(renoir_bluetooth_worker,(void *)(uintptr_t)mode,&worker)==KERN_SUCCESS)thread_deallocate(worker);
 else {renoir_bt_wanted=renoir_bt_running=false;printf("renoir-bt: cannot start Bluetooth probe\n");}
}
#endif
