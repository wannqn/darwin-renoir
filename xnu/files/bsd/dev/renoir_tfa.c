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
#include <sys/redwood_audio.h>
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
static bool tfa_probe_complete, tfa_amplifiers_off;
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
    unsigned off_count=0;
    for(unsigned i=0;i<2;i++) {
        uint16_t revision=0;
        bool ok=tget(0x34+i,3,&revision);
        redwood_wifi_tell("renoir-tfa: address%#x revision%#x %s; amplifiers not started\n",0x34+i,revision,
            !ok?"NO ACK":revision==0x0b73?"TFA9873 confirmed":"unexpected chip");
        uint16_t control=0;
        bool readable=ok && revision==0x0b73 && tget(0x34+i,0,&control);
        bool off=readable && ((control&1)!=0 || (control&8)==0);
        off_count+=off;
        uint16_t mtp=0,re25=0;
        bool calibrated=readable && tget(0x34+i,0xf0,&mtp) && tget(0x34+i,0xf5,&re25) && (mtp&2)!=0;
        redwood_wifi_tell("renoir-tfa: address%#x factory calibration MTP%#x R25C%u mOhm %s (read only)\n",
            0x34+i,mtp,re25,calibrated && re25>=2000 && re25<=20000 ? "valid" : "NOT CONFIRMED");
        redwood_wifi_tell("renoir-tfa: address%#x SYS_CTRL%#x %s\n",0x34+i,control,off ? "amplifier off" : "off state NOT CONFIRMED");
    }
    /* Restore latch before mux/output direction; avoid an unintended pulse. */
    for(unsigned i=0;i<2;i++) {tw(TFA_IO(pins[i]),tfa_io[i]&2);tw(TFA_CFG(pins[i]),tfa_cfg[i]);}
    tfa_amplifiers_off=off_count==2;
    tfa_probe_complete=true;
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

/* Renoir's Tertiary MI2S wire format, from OKX renoir-audio-overlay.dtsi,
 * msm-dai-q6-v2.c and the Android mixer snapshot. Configuration only: no
 * clocks, DEVICE_START, PCM, amplifier power or calibration writes here.
 * RX uses SD1, TX feedback uses SD0; both are stereo S24_LE at 96 kHz.
 */
static void renoir_afe_clock_test(void);
struct renoir_i2s_config {
    uint32_t version;
    uint16_t bits, line, stereo, ws_internal;
    uint32_t rate;
    uint16_t format, reserved;
} __attribute__((packed));
struct renoir_afe_config_packet {
    uint16_t port, bytes;
    uint32_t address_low, address_high, map_handle;
    uint32_t module, param;
    uint16_t size, reserved;
    struct renoir_i2s_config config;
} __attribute__((packed));
_Static_assert(sizeof(struct renoir_i2s_config)==20,"AFE I2S ABI");
_Static_assert(sizeof(struct renoir_afe_config_packet)==48,"AFE in-band ABI");
void renoir_tfa_dsp_up(void) {
    uint32_t probe=0;
    if(!redwood_board_is("renoir") ||
       !PE_parse_boot_argn("renoir_afe_probe",&probe,sizeof(probe)) || (probe<1 || probe>2)) return;
    for(unsigned direction=0;direction<2;direction++) {
        struct renoir_afe_config_packet packet={
            .port=direction ? 0x1005 : 0x1004,
            .bytes=32,.module=0x0001020c,.param=0x0001020d,.size=20,
            .config={.version=1,.bits=24,.line=direction ? 1 : 2,
                     .stereo=1,.ws_internal=1,.rate=96000},
        };
        struct redwood_apr_answer answer={0};
        bool replied=redwood_adsp_apr(4,0,0,0x000100ef,&packet,sizeof(packet),1000,&answer);
        bool accepted=replied && answer.opcode==0x000110e8 && answer.length>=8 &&
                      answer.words[0]==0x000100ef && answer.words[1]==0;
        redwood_wifi_tell("renoir-afe: port%#x stereo S24_LE 96000 SD%u: %s (opcode%#x status%#x); NOT STARTED\n",
            packet.port,direction ? 0 : 1,accepted ? "configuration accepted" : "configuration failed",
            answer.opcode,answer.words[1]);
        if(!accepted) return;
    }
    if(probe==2) renoir_afe_clock_test();
}

/* Bounded, silent interface test. No PCM, amplifier register or reset writes.
 * Clock slots are 32 bits for S24_LE (96k * 2 * 32 = 6.144 MHz).
 */
static bool renoir_afe_command(uint32_t opcode,const void *payload,uint32_t bytes) {
    struct redwood_apr_answer answer={0};
    bool ok=redwood_adsp_apr(4,0,0,opcode,payload,bytes,1000,&answer) &&
        answer.opcode==0x110e8 && answer.length>=8 && answer.words[0]==opcode && answer.words[1]==0;
    redwood_wifi_tell("renoir-afe: command%#x %s (response%#x status%#x)\n",opcode,ok ? "accepted" : "FAILED",answer.opcode,answer.words[1]);
    return ok;
}
static bool renoir_afe_clock(bool on) {
    struct __attribute__((packed)) {
        uint32_t bytes,low,high,handle,module,param;
        uint16_t size,reserved;
        uint32_t version,id,hz;
        uint16_t attribute,root;
        uint32_t enable;
    } packet={.bytes=32,.module=0x1028f,.param=0x10290,.size=20,
              .version=1,.id=0x104,.hz=6144000,.attribute=1,.enable=on};
    _Static_assert(sizeof(packet)==48,"AFE clock ABI");
    redwood_wifi_tell("renoir-afe: tertiary bit clock 6.144MHz %s\n",on ? "ON" : "OFF");
    return renoir_afe_command(0x100f3,&packet,sizeof(packet));
}
static void renoir_afe_clock_test(void) {
    if(!tfa_probe_complete || !tfa_amplifiers_off) {
        redwood_wifi_tell("renoir-afe: silent start refused: both amplifiers must be confirmed off\n");
        return;
    }
    const unsigned pins[4]={120,122,121,124};
    const unsigned mux[4]={1,1,1,3};
    uint32_t cfg[4],io[4];
    bool rx_attempted=false,tx_attempted=false;
    unsigned sck_changes=0,ws_changes=0;
    if(!tfa_tlmm) tfa_tlmm=ml_io_map(TFA_TLMM,0x100000);
    if(!tfa_tlmm) return;
    for(unsigned i=0;i<4;i++) {cfg[i]=tr(TFA_CFG(pins[i]));io[i]=tr(TFA_IO(pins[i]));}
    /* Linux active state: peripheral mux, 8mA, no pull; GPIO OE off. */
    for(unsigned i=0;i<4;i++) tw(TFA_CFG(pins[i]),(mux[i]<<2)|(3u<<6));
    if(!renoir_afe_clock(true)) goto cleanup;
    uint16_t port[2]={0x1004,0};
    rx_attempted=true;
    if(!renoir_afe_command(0x100e5,port,sizeof(port))) goto cleanup;
    port[0]=0x1005;tx_attempted=true;
    if(!renoir_afe_command(0x100e5,port,sizeof(port))) goto cleanup;
    uint32_t last_sck=tr(TFA_IO(120))&1,last_ws=tr(TFA_IO(122))&1;
    for(unsigned i=0;i<20000;i++) {
        uint32_t sck=tr(TFA_IO(120))&1,ws=tr(TFA_IO(122))&1;
        sck_changes+=sck!=last_sck;ws_changes+=ws!=last_ws;last_sck=sck;last_ws=ws;
        delay_for_interval(1,NSEC_PER_USEC);
    }
    redwood_wifi_tell("renoir-afe: clock test SCK transitions%u WS transitions%u; NO PCM, amplifiers untouched\n",sck_changes,ws_changes);
cleanup:;
    bool stopped=true;
    uint16_t stop[2]={0x1005,0};
    /* Stop even on a timeout: a command may have reached the DSP without a reply. */
    if(tx_attempted) stopped=renoir_afe_command(0x100e6,stop,sizeof(stop)) && stopped;
    stop[0]=0x1004;
    if(rx_attempted) stopped=renoir_afe_command(0x100e6,stop,sizeof(stop)) && stopped;
    stopped=renoir_afe_clock(false) && stopped;
    for(unsigned i=0;i<4;i++) {tw(TFA_IO(pins[i]),io[i]&2);tw(TFA_CFG(pins[i]),cfg[i]);}
    redwood_wifi_tell("renoir-afe: test ended, pins restored; DSP stop/clock-off %s\n",stopped ? "accepted" : "NOT ALL ACKNOWLEDGED");
}

bool renoir_tfa_is_off(void) { return tfa_probe_complete && tfa_amplifiers_off; }
