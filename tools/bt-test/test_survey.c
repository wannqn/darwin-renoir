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
static volatile bool renoir_transport_ready=true;
static unsigned mode, board=1, soc=1, maps, reads, uart_reads, fifo_reads, workers, ended;
static unsigned writes, waited;
static uint32_t votes;
static bool clock_emulated, clock_stuck, map_fail;
static uint32_t clock_status=0x80000000, protocol=2, master=2, slave=2;
static int PE_parse_boot_argn(const char *n,void *out,size_t size){assert(!strcmp(n,"bluetooth_probe")&&size==4);*(unsigned*)out=mode;return mode!=0;}
static bool redwood_board_is(const char *n){assert(!strcmp(n,"renoir"));return board;}
static uintptr_t pe_arm_get_soc_base_phys(void){return soc?REDWOOD_SOC_BASE:0;}
static vm_offset_t ml_io_map(uintptr_t addr,size_t size){(void)size;maps++;return map_fail && addr==0x99c000?0:addr;}
static uint32_t rd(vm_offset_t p){
 reads++;
 if(p>=0x99c000 && p<0x9a0000){
  uart_reads++;assert(!(clock_status&0x80000000));
  if(p==0x99c068)return protocol<<8;
  if(p==0x99c800 || p==0x99c804)fifo_reads++;
 }
 if(p==0x152008)return votes;
 if(p==0x11785c)return clock_status;
 if(p==0x117004)return master;
 if(p==0x117008)return slave;
 return 0;
}
static void wr(vm_offset_t p,uint32_t v){
 assert(p==0x152008);assert(((v^votes)&~(1u<<17))==0);writes++;votes=v;
 if(clock_emulated && !clock_stuck)clock_status=(votes&(1u<<17))?0:0x80000000;
}
static void sleep_us(uint32_t us){assert(us==10);waited++;}
static void sleep_ms(uint32_t ms){assert(ms==100 || ms==1000 || ms==10);}
static bool renoir_rpmh_read(const char *name,uint32_t off,uint32_t *v){(void)name;(void)off;(void)v;return false;}
static int current_thread(void){return 1;}
static void thread_terminate(int t){assert(t==1);ended++;}
static void thread_deallocate(int t){assert(t==1);}
static int kernel_thread_start(void(*fn)(void*,wait_result_t),void *p,thread_t *t){workers++;*t=1;fn(p,0);return 0;}
#include "../../xnu/files/bsd/dev/renoir_bluetooth.h"
int main(void){
 renoir_bluetooth_init();assert(!maps&&!workers);
 mode=4;renoir_bluetooth_init();assert(!maps&&!workers);
 mode=1;board=0;renoir_bluetooth_init();assert(!maps);
 board=1;soc=0;renoir_bluetooth_init();assert(!maps);
 soc=1;renoir_bluetooth_init();assert(workers==1&&ended==1&&maps==2&&!uart_reads);
 clock_status=0;master=0x80000000;renoir_bluetooth_init();assert(!uart_reads);
 master=2;slave=0x80000000;renoir_bluetooth_init();assert(!uart_reads);
 slave=2;protocol=1;renoir_bluetooth_init();assert(uart_reads==2&&!fifo_reads);
 protocol=2;renoir_bluetooth_init();assert(fifo_reads==2&&ended==workers);
 assert(!writes);
 mode=2;votes=0;renoir_bluetooth_init();assert(!writes);
 votes=0x3c0;clock_status=0x80000000;clock_emulated=true;
 unsigned before=uart_reads;renoir_bluetooth_init();assert(uart_reads>before && writes==2 && votes==0x3c0);
 clock_stuck=true;before=uart_reads;renoir_bluetooth_init();assert(uart_reads==before && writes==4 && waited==1000);
 clock_stuck=false;map_fail=true;renoir_bluetooth_init();assert(writes==6 && votes==0x3c0);
 map_fail=false;protocol=1;renoir_bluetooth_init();assert(writes==8 && votes==0x3c0);
 protocol=2;votes|=1u<<17;clock_status=0;renoir_bluetooth_init();assert(writes==8 && (votes&(1u<<17)));
 mode=3;renoir_bluetooth_init();assert(writes==8); /* Missing supplies: no controller changes. */
 assert(ended==workers);
 renoir_bluetooth_stop();assert(!renoir_bt_running && !renoir_bt_wanted);
 puts("Bluetooth hardware survey: gates and powered-down UART avoidance passed");
}
