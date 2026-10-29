#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
typedef uintptr_t vm_offset_t;
typedef int wait_result_t;
typedef int thread_t;
#define KERN_SUCCESS 0
#define REDWOOD_SOC_BASE 0x400000
static unsigned mode, board=1, soc=1, maps, reads, uart_reads, fifo_reads, workers, ended;
static uint32_t clock_status=0x80000000, protocol=2, master=2, slave=2;
static int PE_parse_boot_argn(const char *n,void *out,size_t size){assert(!strcmp(n,"bluetooth_probe")&&size==4);*(unsigned*)out=mode;return mode!=0;}
static bool redwood_board_is(const char *n){assert(!strcmp(n,"renoir"));return board;}
static uintptr_t pe_arm_get_soc_base_phys(void){return soc?REDWOOD_SOC_BASE:0;}
static vm_offset_t ml_io_map(uintptr_t addr,size_t size){(void)size;maps++;return addr;}
static uint32_t rd(vm_offset_t p){
 reads++;
 if(p>=0x99c000 && p<0x9a0000){
  uart_reads++;assert(!(clock_status&0x80000000));
  if(p==0x99c068)return protocol<<8;
  if(p==0x99c800 || p==0x99c804)fifo_reads++;
 }
 if(p==0x11785c)return clock_status;
 if(p==0x117004)return master;
 if(p==0x117008)return slave;
 return 0;
}
static int current_thread(void){return 1;}
static void thread_terminate(int t){assert(t==1);ended++;}
static void thread_deallocate(int t){assert(t==1);}
static int kernel_thread_start(void(*fn)(void*,wait_result_t),void *p,thread_t *t){workers++;*t=1;fn(p,0);return 0;}
#include "../../xnu/files/bsd/dev/renoir_bluetooth.h"
int main(void){
 renoir_bluetooth_init();assert(!maps&&!workers);
 mode=2;renoir_bluetooth_init();assert(!maps&&!workers);
 mode=1;board=0;renoir_bluetooth_init();assert(!maps);
 board=1;soc=0;renoir_bluetooth_init();assert(!maps);
 soc=1;renoir_bluetooth_init();assert(workers==1&&ended==1&&maps==2&&!uart_reads);
 clock_status=0;master=0x80000000;renoir_bluetooth_init();assert(!uart_reads);
 master=2;slave=0x80000000;renoir_bluetooth_init();assert(!uart_reads);
 slave=2;protocol=1;renoir_bluetooth_init();assert(uart_reads==2&&!fifo_reads);
 protocol=2;renoir_bluetooth_init();assert(fifo_reads==2&&ended==workers);
 puts("Bluetooth hardware survey: gates and powered-down UART avoidance passed");
}
