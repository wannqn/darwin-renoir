/* Renoir TFA9873 control bus (OKX renoir-sm7350.dtsi and shima-pinctrl.dtsi).
 * GPIO36 SDA/GPIO37 SCL, two devices 0x34/0x35, revision0b73.
 * speaker_probe=1: pin state only; =2: read chip IDs with temporary open-drain
 * GPIO I2C. No amplifier enable, reset, calibration or OTP writes.
 */
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include "renoir_tfa_amp_core.h"
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
static uint16_t tfa_factory_re25[2];
static bool tfa_protection_ready;
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
        if(calibrated && re25>=2000 && re25<=20000) tfa_factory_re25[i]=re25;
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

/* NXP host DSP protocol from OKX tfa_platform_interface_definition.h and
 * tfa98xx.c. RAM-only configuration; no TFA register writes or calibration.
 */
static bool renoir_tfa_dsp_param(uint16_t port,uint32_t module,uint32_t param,const uint8_t *data,uint16_t size) {
    uint8_t packet[16+12+12]={0};
    if(size>12) return false;
    uint32_t value=module;memcpy(packet+16,&value,4);
    value=param;memcpy(packet+20,&value,4);
    uint16_t payload=12+size;
    memcpy(packet,&port,2);memcpy(packet+2,&payload,2);memcpy(packet+24,&size,2);
    memcpy(packet+28,data,size);
    struct redwood_apr_answer answer={0};
    bool ok=redwood_adsp_apr(4,0,0,0x100ef,packet,28+size,1000,&answer) &&
        answer.opcode==0x110e8 && answer.length>=8 && answer.words[0]==0x100ef && answer.words[1]==0;
    redwood_wifi_tell("renoir-tfa-dsp: port%#x module%#x param%#x %s (response%#x status%#x)\n",
        port,module,param,ok ? "accepted" : "REFUSED",answer.opcode,answer.words[1]);
    return ok;
}
bool renoir_tfa_configure_protection(void) {
    if(!redwood_board_is("renoir") || !renoir_tfa_is_off() ||
       !tfa_factory_re25[0] || !tfa_factory_re25[1]) return false;
    uint8_t enabled[4]={1,0,0,0},bypass[4]={0},mute[9]={0,0x81,3,0,0,1,0,0,1};
    uint8_t calibration[9]={0,0x81,5};
    for(unsigned i=0;i<2;i++) {
        uint32_t q16=(uint32_t)tfa_factory_re25[i]*65536u/1000u;
        calibration[3+3*i]=(uint8_t)(q16>>16);
        calibration[4+3*i]=(uint8_t)(q16>>8);
        calibration[5+3*i]=(uint8_t)q16;
    }
    bool ok=renoir_tfa_dsp_param(0x1004,0x1000b911,0x1000b923,bypass,4) &&
        renoir_tfa_dsp_param(0x1005,0x1000b912,0x1000b920,enabled,4) &&
        renoir_tfa_dsp_param(0x1004,0x1000b911,0x1000b921,mute,9) &&
        renoir_tfa_dsp_param(0x1004,0x1000b911,0x1000b921,calibration,9);
    tfa_protection_ready=ok;
    redwood_wifi_tell("renoir-tfa-dsp: protection RAM configuration %s; channels muted, amplifiers still off\n",ok ? "accepted" : "FAILED");
    return ok;
}

/* Amplifier control uses only volatile I2C registers. OTP programming registers
 * are inaccessible to the core. Factory R25C is rechecked after preparation.
 */
static LCK_GRP_DECLARE(tfa_group,"renoir-tfa");
static LCK_MTX_DECLARE(tfa_lock,&tfa_group);
static struct rtfa_amp tfa_amps[2]={{.address=0x34},{.address=0x35}};
static bool tfa_prepared,tfa_running,tfa_broken,tfa_switch_taken;
static uint32_t tfa_switch_cfg,tfa_switch_io;
static uint32_t tfa_pcm_scale=2147483647u;
static void tbus_begin(void) {
    const unsigned pins[2]={36,37};
    for(unsigned i=0;i<2;i++) {
        tfa_cfg[i]=tr(TFA_CFG(pins[i]));tfa_io[i]=tr(TFA_IO(pins[i]));
        tw(TFA_CFG(pins[i]),tfa_cfg[i]&~(TFA_OE|0x3cu));tw(TFA_IO(pins[i]),0);
    }
}
static void tbus_end(void) {
    const unsigned pins[2]={36,37};
    for(unsigned i=0;i<2;i++){tw(TFA_IO(pins[i]),tfa_io[i]&2);tw(TFA_CFG(pins[i]),tfa_cfg[i]);}
}
static bool tput(uint8_t address,uint8_t reg,uint16_t value) {
    bool ok=tstart()&&tsend(address<<1)&&tsend(reg)&&tsend(value>>8)&&tsend(value);
    tstop();return ok;
}
static const struct rtfa_bus tfa_bus={tget,tput};
static void tfa_reset_emergency(void) {
    /* Shared reset held low, never a calibration or OTP operation. */
    tw(TFA_IO(15),0);tw(TFA_CFG(15),TFA_OE|1);
    tfa_broken=true;tfa_running=false;
    redwood_wifi_tell("renoir-tfa: emergency hardware reset asserted\n");
}
static bool tfa_shutdown_locked(void) {
    bool ok=true;
    for(unsigned i=0;i<2;i++) {
        ok=rtfa_shutdown(&tfa_amps[i],&tfa_bus)&&ok;
        ok=tput(0x34+i,0xa1,0)&&ok;ok=tput(0x34+i,0x0f,0)&&ok;
    }
    tfa_running=tfa_prepared=false;tfa_amplifiers_off=ok;
    if(!ok)tfa_reset_emergency();
    if(tfa_switch_taken){tw(TFA_IO(24),tfa_switch_io&2);tw(TFA_CFG(24),tfa_switch_cfg);tfa_switch_taken=false;}
    return ok;
}
bool renoir_tfa_amp_prepare(void) {
    if(!redwood_board_is("renoir") || !tfa_protection_ready || !renoir_tfa_is_off() || tfa_broken)return false;
    uint64_t size=0;const uint8_t *data=redwood_adsp_fw_file("tfa98xx.cnt",&size);
    struct renoir_tfa_container container;struct renoir_tfa_plan plans[2];
    bool valid=data && size<=1024*1024 && renoir_tfa_open(&container,data,(uint32_t)size) &&
        renoir_tfa_stereo(&container,0,&plans[0]) && renoir_tfa_stereo(&container,1,&plans[1]);
    if(!valid){if(data)redwood_adsp_fw_free(data,size);return false;}
    renoir_tfa_amp_volume(240,0);
    lck_mtx_lock(&tfa_lock);tbus_begin();
    tfa_switch_cfg=tr(TFA_CFG(24));tfa_switch_io=tr(TFA_IO(24));tfa_switch_taken=true;
    tw(TFA_IO(24),0);tw(TFA_CFG(24),TFA_OE|1); /* Android stereo speaker switch. */
    bool ok=true;
    for(unsigned i=0;i<2 && ok;i++) {
        ok=rtfa_prepare(&tfa_amps[i],&tfa_bus,&plans[i]);
        uint16_t re25=0,mtp=0;
        ok=ok&&tget(0x34+i,0xf5,&re25)&&tget(0x34+i,0xf0,&mtp)&&re25==tfa_factory_re25[i]&&(mtp&2);
        redwood_wifi_tell("renoir-tfa: address%#x stereo prepare %s, last field%#x, factory R25C%u\n",0x34+i,ok ? "OK" : "FAILED",tfa_amps[i].failed_field,re25);
    }
    tfa_prepared=ok;
    if(!ok)tfa_shutdown_locked();
    tbus_end();lck_mtx_unlock(&tfa_lock);redwood_adsp_fw_free(data,size);return ok;
}
static bool tfa_healthy_locked(bool require_amp) {
    static unsigned observations;
    bool report=observations<4 || observations%25==0;observations++;
    for(unsigned i=0;i<2;i++) {
        uint16_t status=0,amp=0,temp=0,extra=0;
        if(!tget(0x34+i,0x10,&status)||!tget(0x34+i,0x11,&amp)||!tget(0x34+i,0x13,&extra)||!tget(0x34+i,0x16,&temp))return false;
        int c=temp&0x1ff;if(c&0x100)c-=512;
        if(report)redwood_wifi_tell("renoir-tfa: address%#x health status%#x amp%#x manager%#x temp_raw%#x PWM%u\n",
            0x34+i,status,amp,extra,temp,(amp>>14)&1);
        if(!rtfa_status_healthy(status,amp,extra,temp,require_amp)) {
            redwood_wifi_tell("renoir-tfa: address%#x FAULT status%#x amp%#x extra%#x temp%d\n",0x34+i,status,amp,extra,c);return false;
        }
    }
    return true;
}
bool renoir_tfa_amp_healthy(void) {
    lck_mtx_lock(&tfa_lock);tbus_begin();bool ok=!tfa_broken && tfa_running && tfa_healthy_locked(true);
    if(!ok)tfa_shutdown_locked();tbus_end();lck_mtx_unlock(&tfa_lock);return ok;
}
static bool tfa_dsp_mute(bool muted) {
    uint8_t cmd[9]={0,0x81,3,0,0,muted,0,0,muted};
    return renoir_tfa_dsp_param(0x1004,0x1000b911,0x1000b921,cmd,sizeof(cmd));
}
bool renoir_tfa_amp_start(void) {
    if(!tfa_prepared || tfa_broken || !tfa_protection_ready || !tfa_dsp_mute(true))return false;
    delay_for_interval(60,NSEC_PER_MSEC);
    lck_mtx_lock(&tfa_lock);tbus_begin();bool ok=true;
    for(unsigned i=0;i<2 && ok;i++) {
        ok=rtfa_power(&tfa_amps[i],&tfa_bus,false);
        uint16_t status=0;
        for(unsigned ms=0;ok && ms<100;ms++) {
            ok=tget(0x34+i,0x10,&status);if(status&0x40)break;
            delay_for_interval(1,NSEC_PER_MSEC);
        }
        ok=ok&&(status&0x40)&&rtfa_power(&tfa_amps[i],&tfa_bus,true);
    }
    delay_for_interval(20,NSEC_PER_MSEC);
    tfa_running=ok;tfa_amplifiers_off=!ok;
    ok=ok&&tfa_healthy_locked(true);
    if(!ok)tfa_shutdown_locked();tbus_end();lck_mtx_unlock(&tfa_lock);
    if(ok)ok=tfa_dsp_mute(false);
    if(!ok)renoir_tfa_amp_stop();
    redwood_wifi_tell("renoir-tfa: amplifier start %s\n",ok ? "OK" : "FAILED");return ok;
}
void renoir_tfa_amp_stop(void) {
    if(!tfa_tlmm || !tfa_prepared)return;
    if(tfa_dsp_mute(true))delay_for_interval(60,NSEC_PER_MSEC);
    lck_mtx_lock(&tfa_lock);tbus_begin();bool ok=true;
    for(unsigned i=0;i<2;i++) {
        ok=rtfa_field(&tfa_amps[i],&tfa_bus,0x0030,0)&&ok;
        ok=rtfa_field(&tfa_amps[i],&tfa_bus,0x0000,1)&&ok;
    }
    tfa_running=false;tfa_amplifiers_off=ok;
    if(!ok)tfa_shutdown_locked();tbus_end();lck_mtx_unlock(&tfa_lock);
    redwood_wifi_tell("renoir-tfa: amplifiers stopped %s\n",ok ? "OK" : "FAILED");
}
void renoir_tfa_amp_release(void) {
    if(!tfa_tlmm || !tfa_prepared)return;
    renoir_tfa_amp_stop();lck_mtx_lock(&tfa_lock);tbus_begin();
    bool ok=tfa_shutdown_locked();tbus_end();lck_mtx_unlock(&tfa_lock);
    redwood_wifi_tell("renoir-tfa: volatile registers restored %s\n",ok ? "OK" : "RESET");
}
bool renoir_tfa_amp_volume(uint32_t below,unsigned fade_ms) {
    (void)fade_ms;
    if(below<160)below=160; /* At most -20dB; louder operation needs separate characterization. */
    if(below>960)below=960;
    uint64_t scale=2147483647u;
    for(unsigned i=0;i<below;i++)scale=(scale*2116801233u)>>31; /* -1/8dB per step */
    __atomic_store_n(&tfa_pcm_scale,(uint32_t)scale,__ATOMIC_RELEASE);return true;
}
void renoir_tfa_scale_pcm(int16_t *samples,unsigned frames) {
    uint32_t scale=__atomic_load_n(&tfa_pcm_scale,__ATOMIC_ACQUIRE);
    for(unsigned i=0;i<frames*2;i++)samples[i]=(int16_t)(((int64_t)samples[i]*scale)>>31);
}
void renoir_tfa_amp_quiesce(void) {
    if(tfa_tlmm && (tfa_running || tfa_prepared))tfa_reset_emergency();
}
