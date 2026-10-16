/* NXP TFA9873 container metadata, as described by OKX tfa98xx_parameters.h.
 * Parsing only: this file never writes registers, calibration or OTP.
 * The receiver/speaker must use their own Android container, not AW88261 ACF.
 */
#ifndef RENOIR_TFA_CONTAINER_H
#define RENOIR_TFA_CONTAINER_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
struct renoir_tfa_container { const uint8_t *data; uint32_t size; };
struct renoir_tfa_field { uint16_t field, value; };
#define RENOIR_TFA_MAX_FIELDS 64
struct renoir_tfa_plan {
    uint8_t address;
    uint32_t count;
    struct renoir_tfa_field fields[RENOIR_TFA_MAX_FIELDS];
};
static inline uint16_t rtfa_u16(const uint8_t *p) { return p[0] | (uint16_t)p[1] << 8; }
static inline uint32_t rtfa_u32(const uint8_t *p) { return rtfa_u16(p) | (uint32_t)rtfa_u16(p+2) << 16; }
static inline bool rtfa_range(const struct renoir_tfa_container *c, uint32_t at, uint32_t n) {
    return at <= c->size && n <= c->size - at;
}
static inline bool rtfa_string(const struct renoir_tfa_container *c, uint32_t desc, const char *wanted) {
    uint32_t at = desc & 0xffffff;
    if (desc >> 24 != 3 || !rtfa_range(c, at, 1)) return false;
    const uint8_t *end = memchr(c->data + at, 0, c->size - at);
    return end && (!wanted || ((size_t)(end-c->data-at) == strlen(wanted) &&
        memcmp(c->data+at, wanted, strlen(wanted)) == 0));
}
static inline bool renoir_tfa_open(struct renoir_tfa_container *c, const uint8_t *data, uint32_t size) {
    uint32_t crc = ~0u;
    *c = (struct renoir_tfa_container){0};
    if (!data || size < 54 || size > 1024*1024 || memcmp(data,"PM3_01",6) ||
        rtfa_u32(data+6) != size || rtfa_u16(data+40) != 2) return false;
    for (uint32_t i=14; i<size; i++) {
        crc ^= data[i];
        for (unsigned b=0; b<8; b++) crc = (crc>>1) ^ (0xedb88320u & (0u-(crc&1)));
    }
    if (~crc != rtfa_u32(data+10)) return false;
    *c = (struct renoir_tfa_container){data,size};
    return true;
}
static inline bool rtfa_add_field(const struct renoir_tfa_container *c, uint32_t desc, struct renoir_tfa_plan *p) {
    uint32_t at=desc&0xffffff;
    if (desc>>24 != 16 || !rtfa_range(c,at,4) || p->count == RENOIR_TFA_MAX_FIELDS) return false;
    uint16_t value=rtfa_u16(c->data+at),field=rtfa_u16(c->data+at+2);
    unsigned bits=(field&15)+1,shift=(field>>4)&15;
    if (bits+shift>16 || (bits<16 && value>=(1u<<bits))) return false;
    p->fields[p->count++] = (struct renoir_tfa_field){field,value};
    return true;
}
/* Build a volatile-field plan only for the selected normal profile. Calibration
 * profiles and file/command descriptors are never treated as register writes. */
static inline bool renoir_tfa_stereo(const struct renoir_tfa_container *c, unsigned device, struct renoir_tfa_plan *out) {
    struct renoir_tfa_plan p={0};
    if (!c->data || device>=2 || !rtfa_range(c,46+4*device,4)) return false;
    uint32_t desc=rtfa_u32(c->data+46+4*device),at=desc&0xffffff,profile=0;
    if (desc>>24 != 0 || !rtfa_range(c,at,12)) return false;
    uint32_t count=c->data[at];
    if (!rtfa_range(c,at+12,4*count) || c->data[at+1]!=0 ||
        c->data[at+2] != 0x34+device || !rtfa_string(c,rtfa_u32(c->data+at+8),device?"SPK":"RCV")) return false;
    p.address=c->data[at+2];
    for (unsigned i=0; i<count; i++) {
        desc=rtfa_u32(c->data+at+12+4*i);
        uint32_t off=desc&0xffffff,type=desc>>24;
        if (type==16) { if(!rtfa_add_field(c,desc,&p)) return false; }
        else if (type==1) {
            if (!rtfa_range(c,off,8) || rtfa_u16(c->data+off+2)!=0x1234 || !c->data[off] ||
                !rtfa_range(c,off+8,4*(c->data[off]-1u))) return false;
            if (rtfa_string(c,rtfa_u32(c->data+off+4),"stereo")) {
                if (profile) return false;
                profile=off;
            }
        } else if (type==5) { /* firmware patch metadata is validated, not executed */
            if (!rtfa_range(c,off,8) || !rtfa_string(c,rtfa_u32(c->data+off),NULL) ||
                !rtfa_range(c,off+8,rtfa_u32(c->data+off+4))) return false;
        } else if (type==25) { if (!rtfa_range(c,off,6)) return false; }
        else return false;
    }
    if (!profile) return false;
    for (unsigned i=0; i<c->data[profile]-1u; i++) {
        desc=rtfa_u32(c->data+profile+8+4*i);
        if (desc>>24 == 17) break; /* end of profile settings, default section follows */
        if (!rtfa_add_field(c,desc,&p)) return false;
    }
    *out=p;
    return true;
}
#endif
