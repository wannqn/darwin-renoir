/* TFA9873 volatile register startup; no MTP programming or calibration.
 * Register values and bitfields follow OKX tfa9873_specific and stereo container.
 */
#ifndef RENOIR_TFA_AMP_CORE_H
#define RENOIR_TFA_AMP_CORE_H
#include "renoir_tfa_container.h"
/* OTDS/UVDS/OVDS and individual OCPOK bits are asserted when healthy,
 * as in OKX tfa_status(). AMPS can be off while zero samples invoke idle.
 * TEMPS=0x100 is an unavailable ADC reading, including during PWM transitions.
 * It is not a thermal alarm; OTDS is checked independently even then.
 */
static inline bool rtfa_status_healthy(uint16_t status,uint16_t amp,uint16_t extra,uint16_t temp,bool operating) {
    int c=temp&0x1ff;if(c&0x100)c-=512;
    if((status&0x54)!=0x54 || (status&0x520) || !(amp&0x40) ||
       (extra&0x10f)!=0x10f || (operating && !(extra&0x8000)))return false;
    if((temp&0x1ff)==0x100)return true;
    return c>=-40 && c<=80;
}
struct rtfa_bus {bool (*read)(uint8_t,uint8_t,uint16_t*);bool (*write)(uint8_t,uint8_t,uint16_t);};
struct rtfa_saved {uint8_t reg;uint16_t value;};
struct rtfa_amp {uint8_t address;unsigned count;struct rtfa_saved saved[64];bool prepared,started;uint16_t failed_field;};
static bool rtfa_write_allowed(uint8_t reg) {
    return (reg<0x90 && !(reg>=0x10 && reg<=0x1f) && reg!=3 && reg!=0x0f) || reg==0xd5 || reg==0xf9;
}
static bool rtfa_write(struct rtfa_amp *a,const struct rtfa_bus *b,uint8_t reg,uint16_t value) {
    uint16_t old,actual;
    if(!rtfa_write_allowed(reg)||!b->read(a->address,reg,&old))return false;
    if(reg==0xf9 && ((old^value)&~2u))return false; /* only container f910 volatile shadow bit */
    unsigned i;
    for(i=0;i<a->count;i++)if(a->saved[i].reg==reg)break;
    if(i==a->count){if(i==64)return false;a->saved[a->count++]=(struct rtfa_saved){reg,old};}
    if(reg==0){value&=~0x1802u;if(!a->prepared)value=(value|1)&~8u;} /* Never I2CR / OCP bypass / OCP testing. */
    if(reg==1)value&=~0x4000u; /* FAIM protected. */
    return b->write(a->address,reg,value)&&b->read(a->address,reg,&actual)&&actual==value;
}
static bool rtfa_field(struct rtfa_amp *a,const struct rtfa_bus *b,uint16_t field,uint16_t value) {
    unsigned shift=(field>>4)&15,bits=(field&15)+1;
    uint16_t old,mask=(uint16_t)(((1u<<bits)-1u)<<shift);
    if(shift+bits>16 || (bits<16 && value>=(1u<<bits)))return false;
    if(!b->read(a->address,field>>8,&old))return false;
    uint16_t next=(old&~mask)|((value<<shift)&mask);
    if(!rtfa_write_allowed(field>>8)) {
        /* MTP shadow bits are only compared; never written. */
        return next==old;
    }
    return rtfa_write(a,b,field>>8,next);
}
static bool rtfa_shutdown(struct rtfa_amp *a,const struct rtfa_bus *b) {
    uint16_t ctrl=0;bool ok=b->read(a->address,0,&ctrl);
    if(ok)ok=b->write(a->address,0,(ctrl|1)&~0x8u);
    if(ok){uint16_t check=0;ok=b->read(a->address,0,&check)&&(check&1)&&!(check&8);}
    if(!ok)return false; /* Caller asserts shared hardware reset on a bus failure. */
    uint16_t key=0;
    ok=b->write(a->address,0x0f,0x5a6b)&&b->read(a->address,0xfb,&key)&&
        b->write(a->address,0xa0,key^0x5a)&&b->write(a->address,0xa1,0)&&ok;
    while(a->count){struct rtfa_saved v=a->saved[--a->count];
        if(v.reg==1)v.value&=~0x4000u;
        uint16_t check=0;
        if(!b->write(a->address,v.reg,v.value)||!b->read(a->address,v.reg,&check)||check!=v.value)ok=false;
    }
    ok=b->write(a->address,0xa1,0)&&ok;ok=b->write(a->address,0x0f,0)&&ok;
    a->prepared=a->started=false;return ok;
}
static bool rtfa_prepare(struct rtfa_amp *a,const struct rtfa_bus *b,const struct renoir_tfa_plan *plan) {
    a->prepared=a->started=false;
    uint16_t rev=0,ctrl=0;
    if(plan->address!=a->address || !b->read(a->address,3,&rev)||rev!=0x0b73 ||
       !b->read(a->address,0,&ctrl) || !(ctrl&1) || (ctrl&8))return false;
    /* Validate every read-only/OTP shadow field before the first write. */
    for(unsigned i=0;i<plan->count;i++) {
        uint16_t field=plan->fields[i].field,value=plan->fields[i].value,old=0;
        if(!rtfa_write_allowed(field>>8)) {
            unsigned shift=(field>>4)&15,bits=(field&15)+1;
            if(!b->read(a->address,field>>8,&old)||((old>>shift)&((1u<<bits)-1))!=value){a->failed_field=field;return false;}
        }
    }
    uint16_t key=0;
    if(!b->write(a->address,0x0f,0x5a6b)||!b->read(a->address,0xfb,&key)||
       !b->write(a->address,0xa0,key^0x5a)||!b->write(a->address,0xa1,0))return false;
    static const struct {uint8_t reg;uint16_t value;} optimal[]={
        {2,0x0628},{0x61,0x0183},{0x63,0x005a},{0x6f,0x0083},{0x70,0xa3fb},
        {0x73,0x0187},{0x83,0x009a},{0x85,0x0380},{0xd5,0x004d}};
    bool ok=true;
    for(unsigned i=0;ok && i<sizeof(optimal)/sizeof(optimal[0]);i++){a->failed_field=(uint16_t)optimal[i].reg<<8|15;ok=rtfa_write(a,b,optimal[i].reg,optimal[i].value);}
    for(unsigned i=0;ok && i<plan->count;i++){
        a->failed_field=plan->fields[i].field;
        ok=rtfa_field(a,b,plan->fields[i].field,plan->fields[i].value);
    }
    if(ok)ok=rtfa_field(a,b,0x0480,0)&&rtfa_field(a,b,0x2000,1); /* FSSYNCEN off, TDM enabled */
    bool closed=b->write(a->address,0xa1,0)&&b->write(a->address,0x0f,0);
    a->prepared=ok&&closed;return a->prepared;
}
static bool rtfa_power(struct rtfa_amp *a,const struct rtfa_bus *b,bool amplify) {
    if(!a->prepared)return false;
    if(!rtfa_field(a,b,0x0000,0)||!rtfa_field(a,b,0x0120,1)||!rtfa_field(a,b,0x0030,amplify))return false;
    a->started=amplify;return true;
}
#endif
