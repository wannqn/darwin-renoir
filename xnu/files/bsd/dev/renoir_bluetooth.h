/* Renoir-only, opt-in Bluetooth hardware survey. Included by redwood_wifi.c.
 * Shima GCC: UART SE15 is wrapper 0 SE7 (not wrapper 1). No writes, reset,
 * clock votes, firmware download or publication of a fictitious HCI device.
 */
#ifndef RENOIR_BLUETOOTH_H
#define RENOIR_BLUETOOTH_H
static void
renoir_bluetooth_survey_run(void)
{
 vm_offset_t gcc=ml_io_map(0x00100000,0x60000);
 vm_offset_t pins=ml_io_map(0x0f100000,0x100000);
 if(!gcc || !pins){printf("renoir-bt: register mapping failed\n");return;}
 uint32_t vote=rd(gcc+0x52008), status=rd(gcc+0x1785c);
 printf("renoir-bt: UART SE15/wrap0-S7: votes %#x branch %#x; no writes\n",vote,status);
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
  return;
 }
 vm_offset_t uart=ml_io_map(0x0099c000,0x4000);
 if(!uart){printf("renoir-bt: UART mapping failed\n");return;}
 uint32_t rev=rd(uart+0x68), protocol=(rev>>8)&0xff;
 printf("renoir-bt: UART firmware %#x protocol %u (UART=2); FIFO disabled %#x\n",rev,protocol,rd(uart+0x64));
 if(protocol!=2){printf("renoir-bt: no UART firmware; no controller command sent\n");return;}
 printf("renoir-bt: UART status %#x clock M %#x S %#x; hardware parameters %#x/%#x\n",
  rd(uart+0x40),rd(uart+0x48),rd(uart+0x4c),rd(uart+0xe24),rd(uart+0xe28));
 printf("renoir-bt: UART TX/RX FIFO status %#x/%#x; no data consumed\n",rd(uart+0x800),rd(uart+0x804));
}
static void
renoir_bluetooth_survey(void *unused, wait_result_t result)
{
 (void)unused; (void)result;
 renoir_bluetooth_survey_run();
 thread_terminate(current_thread());
}
static void
renoir_bluetooth_init(void)
{
 uint32_t mode=0;
 if(!PE_parse_boot_argn("bluetooth_probe",&mode,sizeof(mode)) || !mode)return;
 if(mode!=1 || !redwood_board_is("renoir") || pe_arm_get_soc_base_phys()!=REDWOOD_SOC_BASE){
  printf("renoir-bt: refused: bluetooth_probe=1 requires physical renoir\n");return;
 }
 thread_t worker;
 if(kernel_thread_start(renoir_bluetooth_survey,NULL,&worker)==KERN_SUCCESS)thread_deallocate(worker);
 else printf("renoir-bt: cannot start hardware survey\n");
}
#endif
