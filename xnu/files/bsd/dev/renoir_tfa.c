/* Renoir TFA9873 control bus (OKX renoir-sm7350.dtsi and shima-pinctrl.dtsi).
 * GPIO36 SDA/GPIO37 SCL, two devices 0x34/0x35, revision0b73.
 * speaker_probe=1: pin state only; =2: read chip IDs with temporary open-drain
 * GPIO I2C. No amplifier enable, reset, calibration or OTP writes.
 */
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include <sys/redwood_input.h>
#include <sys/systm.h>
extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern kern_return_t thread_terminate(thread_t);
#define TFA_TLMM 0x0f100000ul
#define TFA_SDA 36
#define TFA_SCL 37
#define TFA_CFG(n) (0x1000u*(n))
#define TFA_IO(n) (TFA_CFG(n)+4)
#define TFA_OE (1u<<9)
static vm_offset_t tfa_tlmm;
static uint32_t tfa_cfg[2], tfa_io[2];
static unsigned tfa_probe_level;
static uint32_t tr(unsigned off) { return *(volatile uint32_t *)(tfa_tlmm+off); }
static void tw(unsigned off,uint32_t value) { *(volatile uint32_t *)(tfa_tlmm+off)=value; __asm__ volatile("dsb sy" ::: "memory"); }
static void tdelay(void) { delay_for_interval(4,NSEC_PER_USEC); }
/* Always release a high level: never drive SDA or SCL high. */
static void tline(unsigned pin,bool high) {
    uint32_t cfg=tr(TFA_CFG(pin));
    if (high) tw(TFA_CFG(pin),cfg&~TFA_OE);
    else { tw(TFA_IO(pin),0); tw(TFA_CFG(pin),cfg|TFA_OE); }
    tdelay();
}
static bool tclock(void) {
    tline(TFA_SCL,true);
    for(unsigned i=0;i<250;i++) { if(tr(TFA_IO(TFA_SCL))&1) return true; tdelay(); }
    return false;
}
static void tstop(void) {
    tline(TFA_SCL,false);tline(TFA_SDA,false);(void)tclock();tline(TFA_SDA,true);
}
static bool tstart(void) {
    tline(TFA_SDA,true);
    if(!tclock() || !(tr(TFA_IO(TFA_SDA))&1)) return false;
    tline(TFA_SDA,false);tline(TFA_SCL,false);return true;
}
static bool tsend(uint8_t value) {
    for(unsigned i=0;i<8;i++) {
        tline(TFA_SDA,(value&0x80)!=0);
        if(!tclock())return false;
        tline(TFA_SCL,false);value<<=1;
    }
    tline(TFA_SDA,true);
    if(!tclock())return false;
    bool ack=(tr(TFA_IO(TFA_SDA))&1)==0;
    tline(TFA_SCL,false);return ack;
}
static bool treceive(uint8_t *value,bool last) {
    uint8_t data=0;tline(TFA_SDA,true);
    for(unsigned i=0;i<8;i++) {
        if(!tclock())return false;
        data=(data<<1)|(tr(TFA_IO(TFA_SDA))&1);tline(TFA_SCL,false);
    }
    tline(TFA_SDA,last); /* ACK first byte, NACK last */
    if(!tclock())return false;
    tline(TFA_SCL,false);tline(TFA_SDA,true);*value=data;return true;
}
static bool tget(uint8_t address,uint8_t reg,uint16_t *value) {
    uint8_t high=0,low=0;
    bool ok=tstart()&&tsend(address<<1)&&tsend(reg)&&tstart()&&tsend((address<<1)|1)&&
        treceive(&high,false)&&treceive(&low,true);
    tstop();if(ok)*value=(uint16_t)high<<8|low;return ok;
}
static void tfa_probe(__unused void *arg,__unused wait_result_t result) {
    const unsigned pins[2]={TFA_SDA,TFA_SCL};
    tfa_tlmm=ml_io_map(TFA_TLMM,0x100000);
    if(!tfa_tlmm) goto done;
    redwood_wifi_tell("renoir-tfa: GPIO36 SDA cfg%#x IO%#x, GPIO37 SCL cfg%#x IO%#x; reset15 cfg%#x IO%#x\n",
        tr(TFA_CFG(TFA_SDA)),tr(TFA_IO(TFA_SDA)),tr(TFA_CFG(TFA_SCL)),tr(TFA_IO(TFA_SCL)),tr(TFA_CFG(15)),tr(TFA_IO(15)));
    if(tfa_probe_level<2) goto done;
    for(unsigned i=0;i<2;i++) {
        tfa_cfg[i]=tr(TFA_CFG(pins[i]));tfa_io[i]=tr(TFA_IO(pins[i]));
        /* GPIO mux, existing pull/drive strength, output disabled. */
        tw(TFA_CFG(pins[i]),tfa_cfg[i]&~(TFA_OE|0x3cu));
        tw(TFA_IO(pins[i]),0);
    }
    for(unsigned i=0;i<2;i++) {
        uint16_t revision=0;
        bool ok=tget(0x34+i,3,&revision);
        redwood_wifi_tell("renoir-tfa: address%#x revision%#x %s; amplifiers not started\n",0x34+i,revision,
            !ok?"NO ACK":revision==0x0b73?"TFA9873 confirmed":"unexpected chip");
    }
    /* Restore latch before mux/output direction; avoid an unintended pulse. */
    for(unsigned i=0;i<2;i++) {tw(TFA_IO(pins[i]),tfa_io[i]&2);tw(TFA_CFG(pins[i]),tfa_cfg[i]);}
done:
    thread_terminate(current_thread());
}
void renoir_tfa_init(void);
void renoir_tfa_init(void) {
    uint32_t on=0;thread_t thread;
    if(!redwood_board_is("renoir")||!PE_parse_boot_argn("speaker_probe",&on,sizeof(on))||on==0)return;
    tfa_probe_level=on;
    if(kernel_thread_start(tfa_probe,NULL,&thread)==KERN_SUCCESS)thread_deallocate(thread);
}
