/* Renoir PM8350B HV haptics: read-only haptic=1, finite test tap=4, iOS actuator=5.
 * OKX xiaomi-sm7350-common.dtsi / pm8350b.dtsi, qcom-hv-haptics.c.
 * SID3 CFG f000, PATTERN f100, BOOST f200. Independent of Redwood AW86927.
 */
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include <sys/conf.h>
#include <sys/errno.h>
#include <sys/uio.h>
#include <miscfs/devfs/devfs.h>
#include "renoir_haptic_core.h"
#include <sys/redwood_audio.h>
#include <sys/redwood_input.h>
extern vm_offset_t ml_io_map(vm_offset_t,vm_size_t);
extern kern_return_t thread_terminate(thread_t);
static vm_offset_t rh_core,rh_owner,rh_observer,rh_channel_write[2];
static unsigned rh_channels[2]={512,512};
static uint32_t rh_level;
static bool rh_can_write,rh_leaving,rh_serving;
static uint32_t rh_running;
static uint32_t rh_pending_peak;
static struct rhh_state rh_state;
static inline uint32_t rh_read32(vm_offset_t p) { return *(volatile uint32_t *)p; }
static bool rh_read(unsigned channel,uint8_t reg,uint8_t *data,unsigned count) {
    if(channel>=512 || !count || count>8 || (unsigned)reg+count>256)return false;
    vm_offset_t p=rh_observer+0x80UL*channel;
    uint64_t limit;nanoseconds_to_absolutetime(2000ull*NSEC_PER_USEC,&limit);
    for(unsigned retry=0;retry<3;retry++) {
        if(!rh_leaving)redwood_spmi_lock();
        *(volatile uint32_t *)p=(1u<<27)|((uint32_t)reg<<4)|(count-1);
        __asm__ volatile("dsb sy");
        uint64_t start=mach_absolute_time();uint32_t status;
        do {status=rh_read32(p+8);}while(!(status&1) && mach_absolute_time()-start<limit);
        uint32_t a=rh_read32(p+0x18),b=count>4?rh_read32(p+0x1c):0;
        if(!rh_leaving)redwood_spmi_unlock();
        if(!(status&1) || (status&6))return false;
        if(status&8)continue;
        for(unsigned i=0;i<count;i++)data[i]=(i<4?a:b)>>(8*(i%4));
        return true;
    }
    return false;
}
static bool rh_get(uint16_t addr,uint8_t *value) {
 unsigned m=(addr>>8)==0xf0?0:(addr>>8)==0xf1?1:2;
 return m<2 && rh_read(rh_channels[m],addr&255,value,1);
}
static bool rh_put(uint16_t addr,uint8_t value) {
 unsigned m=(addr>>8)==0xf0?0:(addr>>8)==0xf1?1:2;
 if(!rh_can_write || m>1 || !rhh_allowed(addr) || !rh_channel_write[m] ||
    ((rh_read32(rh_core+0x900+4*rh_channels[m])>>8)&0xfff)!=(0x3f0+m) ||
    (rh_read32(rh_owner+0x700+4*rh_channels[m])&7)!=0)return false;
 vm_offset_t p=rh_channel_write[m];
 uint64_t limit;nanoseconds_to_absolutetime(2000ull*NSEC_PER_USEC,&limit);
 for(unsigned retry=0;retry<3;retry++) {
  if(!rh_leaving)redwood_spmi_lock();
  *(volatile uint32_t *)(p+0x10)=value;
  __asm__ volatile("dsb sy");
  *(volatile uint32_t *)p=((uint32_t)(addr&255)<<4);
  __asm__ volatile("dsb sy");
  uint64_t start=mach_absolute_time();uint32_t status;
  do {status=rh_read32(p+8);}while(!(status&1) && mach_absolute_time()-start<limit);
  if(!rh_leaving)redwood_spmi_unlock();
  if(!(status&1)||(status&6))return false;
  if(status&8)continue;return true;
 }
 return false;
}
static const struct rhh_bus rh_bus={rh_get,rh_put};
static uint64_t rh_us(void) {uint64_t ns;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000;}
static int rh_open(dev_t dev,int flags,int type,proc_t p) {(void)dev;(void)flags;(void)type;(void)p;return rh_serving && !rh_leaving?0:ENXIO;}
static int rh_uio_write(dev_t dev,struct uio *uio,int flags) {
 (void)dev;(void)flags;
 if(!rh_serving || rh_leaving)return ENXIO;
 if((uio_resid(uio)&1) || uio_resid(uio)>65536)return EINVAL;
 int16_t samples[128];uint32_t peak=0;
 while(uio_resid(uio)) {
  unsigned n=uio_resid(uio)>sizeof(samples)?sizeof(samples):(unsigned)uio_resid(uio);
  int err=uiomove((caddr_t)samples,n,uio);if(err)return err;
  for(unsigned i=0;i<n/2;i++){int v=samples[i];uint32_t a=v<0?-v:v;if(a>peak)peak=a;}
 }
 uint32_t old=__atomic_load_n(&rh_pending_peak,__ATOMIC_RELAXED);
 while(peak>old && !__atomic_compare_exchange_n(&rh_pending_peak,&old,peak,false,__ATOMIC_RELEASE,__ATOMIC_RELAXED)){}
 return 0;
}
static const struct cdevsw rh_cdevsw={.d_open=rh_open,.d_close=rh_open,.d_read=eno_rdwrt,.d_write=rh_uio_write,
 .d_ioctl=eno_ioctl,.d_stop=eno_stop,.d_reset=eno_reset,.d_select=eno_select,.d_mmap=eno_mmap,.d_strategy=eno_strat,
 .d_type=D_TTY};
static void rh_serve(void) {
 int major=cdevsw_add(-1,&rh_cdevsw);
 if(major<0 || !devfs_make_node(makedev(major,0),DEVFS_CHAR,UID_ROOT,GID_WHEEL,0666,"redwood-haptic"))return;
 rh_serving=true;uint64_t stop_at=0,next_at=0,burst=0;unsigned taps=0;
 redwood_wifi_tell("renoir-haptic: iOS actuator ready, finite 40ms patterns, at most one per100ms\n");
 while(!rh_leaving) {
  uint64_t now=rh_us();uint32_t peak=__atomic_exchange_n(&rh_pending_peak,0,__ATOMIC_ACQUIRE);
  if(rh_state.playing && now>=stop_at) {if(!rhh_stop(&rh_state,&rh_bus))break;next_at=now+60000;}
  if(!rh_state.playing && peak>=256 && now>=next_at) {
   if(burst && now-burst>=500000) {next_at=now+500000;burst=0;continue;}
   if(!burst || now-burst>1000000)burst=now;
   if(!rhh_start(&rh_state,&rh_bus))break;stop_at=now+40000;taps++;
   if(taps<12)redwood_wifi_tell("renoir-haptic: iOS tap%u peak%u\n",taps,peak);
  }
  if(rh_state.playing) {uint8_t fault;if(!rh_get(0xf00c,&fault)||(fault&7))break;}
  delay_for_interval(5,NSEC_PER_MSEC);
 }
 rh_serving=false;redwood_wifi_tell("renoir-haptic: actuator stopped, %u taps, register %#x\n",taps,rh_state.failed_reg);
}
static void rh_probe(void *unused,wait_result_t result) {
    (void)unused;(void)result;
    if(rh_leaving){thread_terminate(current_thread());return;}
    __atomic_store_n(&rh_running,1,__ATOMIC_RELEASE);
    rh_core=ml_io_map(0x0c440000,0x1100);
    rh_owner=ml_io_map(0x0c40a000,0x1000);
    rh_observer=ml_io_map(0x0e600000,0x10000);
    if(!rh_core || !rh_owner || !rh_observer)goto out;
    uint32_t version=rh_read32(rh_core);
    if(version<0x50000000 || version>=0x70000000) {
        redwood_wifi_tell("renoir-haptic: unsupported SPMI arbiter %#x; no writes\n",version);goto out;
    }
    static const uint8_t cfg_regs[]={0x01,0x04,0x05,0x0c,0x46,0x48,0x49,0x4a,0x4c,0x50,0x51,0x58,0x5c,0x5d};
    static const uint8_t pattern_regs[]={0x01,0x04,0x05,0x26,0x30,0x31};
    for(unsigned module=0;module<3;module++) {
        unsigned id=0x3f0+module,channel=512;
        for(unsigned i=0;i<512;i++)if(((rh_read32(rh_core+0x900+4*i)>>8)&0xfff)==id){channel=i;break;}
        if(channel==512){redwood_wifi_tell("renoir-haptic: no channel for PPID %#x\n",id);continue;}
        unsigned owner=rh_read32(rh_owner+0x700+4*channel)&7;
        if(module<2) {
            rh_channels[module]=channel;
            if(rh_level>=4 && owner==0)rh_channel_write[module]=ml_io_map(0x0c600000UL+0x10000UL*channel,0x1000);
        }
        redwood_wifi_tell("renoir-haptic: PPID %#x channel%u owner%u (read only)\n",id,channel,owner);
        const uint8_t *regs=module==0?cfg_regs:pattern_regs;
        unsigned n=module==0?sizeof(cfg_regs):module==1?sizeof(pattern_regs):3;
        for(unsigned i=0;i<n;i++) {
            uint8_t value;
            if(!rh_read(channel,regs[i],&value,1)){redwood_wifi_tell("renoir-haptic: PPID %#x reg%#x read refused\n",id,regs[i]);break;}
            redwood_wifi_tell("renoir-haptic: PPID %#x reg%#x = %#x\n",id,regs[i],value);
        }
    }
    if(!rh_leaving && rh_level>=4 && rh_channels[0]<512 && rh_channels[1]<512 && rh_channel_write[0] && rh_channel_write[1]) {
        uint32_t mv;bool enabled;
        if(!redwood_renoir_haptic_supply_vote(true) || !redwood_renoir_haptic_supply(&mv,&enabled)) {
            redwood_wifi_tell("renoir-haptic: external BOB status unavailable, no motor writes\n");goto out;
        }
        redwood_wifi_tell("renoir-haptic: external BOB %umV enabled%u, APPS vote only, other clients preserved\n",mv,enabled);
        rh_can_write=true;
        if(rhh_prepare(&rh_state,&rh_bus,mv,enabled)) {
            redwood_wifi_tell("renoir-haptic: finite pattern prepared at1650mV\n");
            if(rh_level==5)rh_serve();
            else if(rhh_start(&rh_state,&rh_bus)) {
                delay_for_interval(40,NSEC_PER_MSEC);
                uint8_t fault=0xff;bool healthy=rh_get(0xf00c,&fault) && !(fault&7);
                bool stopped=rhh_stop(&rh_state,&rh_bus);
                redwood_wifi_tell("renoir-haptic: test tap healthy%u stopped%u fault%#x\n",healthy,stopped,fault);
            }
        } else redwood_wifi_tell("renoir-haptic: prepare refused, register %#x\n",rh_state.failed_reg);
        bool restored=rhh_restore(&rh_state,&rh_bus);rh_can_write=false;
        redwood_wifi_tell("renoir-haptic: volatile register restore %s\n",restored?"OK":"FAILED");
    }
out:
    if(rh_level>=4)redwood_wifi_tell("renoir-haptic: APPS supply vote restore %s\n",redwood_renoir_haptic_supply_vote(false)?"OK":"FAILED");
    redwood_wifi_tell("renoir-haptic: probe/worker complete\n");
    __atomic_store_n(&rh_running,0,__ATOMIC_RELEASE);
    thread_terminate(current_thread());
}
void renoir_haptic_init(void) {
    uint32_t level=0;thread_t t;
    if(!redwood_board_is("renoir"))return;
    bool requested=PE_parse_boot_argn("haptic",&level,sizeof(level));
    redwood_wifi_tell("renoir-haptic: init, requested%u level%u\n",requested,level);
    if(!requested || !level)return;
    if(level!=1 && level!=4 && level!=5){redwood_wifi_tell("renoir-haptic: use haptic=1(read),4(tap),5(iOS)\n");return;}
    rh_level=level;
    kern_return_t kr=kernel_thread_start(rh_probe,NULL,&t);
    if(kr==KERN_SUCCESS)thread_deallocate(t);
    else redwood_wifi_tell("renoir-haptic: cannot start probe thread: %d\n",kr);
}

void renoir_haptic_quiesce(void) {
 rh_leaving=true;rh_serving=false;
 if(ml_get_interrupts_enabled()) {
  for(unsigned ms=0;ms<250 && __atomic_load_n(&rh_running,__ATOMIC_ACQUIRE);ms+=5)delay_for_interval(5,NSEC_PER_MSEC);
 }
 /* A panic may have stopped the worker CPU. The finite pattern also ends in hardware. */
 if(rh_can_write)(void)rh_put(0xf04c,2);
}
