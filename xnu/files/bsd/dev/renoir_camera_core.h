/* Renoir Titan580 register sequences, from OKX cam_vfe_lite48x.h,
 * cam_vfe_top_ver3.c, cam_vfe_bus_ver3.c and cam_csiphy_1_2_3_hwreg.h.
 * Linux selects the 480 register map for lite580, and PHY1.2.3 tables for 1.2.4.
 * Portable callbacks let host tests execute the exact sequence and inject faults.
 */
#ifndef RENOIR_CAMERA_CORE_H
#define RENOIR_CAMERA_CORE_H
#include <stdint.h>
#include <stdbool.h>
struct rcam_io {
    void *context;
    bool (*put)(void *, uint32_t, uint32_t, bool);
    bool (*wait)(void *, uint32_t, uint32_t, uint32_t, uint32_t);
    void (*delay)(void *, uint32_t);
    uint32_t (*get)(void *, uint32_t);
};
static inline bool rcam_restore_put(const struct rcam_io *io, uint32_t reg, uint32_t value)
{
    if(io->put(io->context,reg,value,false))return true;
    (void)io->put(io->context,reg,value,false); /* best effort after a partial transfer */
    return false;
}
/* One APPS TCS transaction. Caller holds the shared RPMh mutex. Offsets are
 * relative to one active TCS; preserve its programming and never replay TRIGGER. */
static inline bool rcam_tcs_transfer(const struct rcam_io *io, uint32_t address,
    bool write, uint32_t *value)
{
    static const uint32_t regs[]={0,0x10,0x14,0x1c,0x30,0x34,0x38};
    uint32_t saved[sizeof(regs)/sizeof(regs[0])];
    if (!value || !io->wait(io->context,0x18,1,1,200000)) return false;
    for(unsigned i=0;i<sizeof(regs)/sizeof(regs[0]);i++)saved[i]=io->get(io->context,regs[i]);
    saved[2]&=~(1u<<24);
    bool ok=io->put(io->context,0x14,0,false) && io->put(io->context,0x1c,0,false) &&
        io->put(io->context,8,1,false) &&
        io->put(io->context,0x30,write?0x10108:0x108,false) &&
        io->put(io->context,0x34,address,false) &&
        (!write || io->put(io->context,0x38,*value,false)) &&
        io->put(io->context,0x10,1,false) && io->put(io->context,0x1c,1,false) &&
        io->put(io->context,0,saved[0]|1,false) &&
        io->put(io->context,0x14,1u<<16,false) &&
        io->put(io->context,0x14,(1u<<16)|(1u<<24),false) &&
        io->wait(io->context,4,1,1,200000);
    ok=ok && (io->get(io->context,0x3c)&0x10100)==0x10100;
    if(ok && !write)*value=io->get(io->context,0x40);
    bool restored=rcam_restore_put(io,0x14,0);
    restored&=rcam_restore_put(io,0x1c,0);
    restored&=rcam_restore_put(io,8,1);
    /* Restore CONTROL last, after the old enable mask and commands. */
    for(unsigned i=0;i<sizeof(regs)/sizeof(regs[0]);i++)
        if(i!=2)restored&=rcam_restore_put(io,regs[i],saved[i]);
    restored&=rcam_restore_put(io,0x14,saved[2]);
    return ok && restored;
}
static inline void rcam_ife_stop(const struct rcam_io *io)
{
    (void)io->put(io->context, 0x1c00, 0, false);
    (void)io->put(io->context, 0x20, 1, false);
    (void)io->put(io->context, 0x28, 0, false);
    (void)io->put(io->context, 0x2c, 0, false);
    (void)io->put(io->context, 0x30, 0, false);
    (void)io->put(io->context, 0x1a18, 0, false);
    (void)io->put(io->context, 0x1a1c, 0, false);
}
static inline bool rcam_ife_start(const struct rcam_io *io, uint64_t address,
    uint32_t frame_bytes, uint32_t frame_inc)
{
    /* Frame-mode writes packed CSI bytes. There is no bus-v2 address offset. */
    if (!frame_bytes || address > UINT32_MAX || (address & 15) ||
        address + frame_bytes > (1ull << 32) || (frame_inc && frame_inc != frame_bytes)) return false;
    if (!io->put(io->context, 0x28, 0x20000, false) ||
        !io->put(io->context, 0x0c, 2, false) ||
        !io->wait(io->context, 0x40, 0x20000, 0x20000, 100000)) goto fail;
    const struct { uint32_t reg, value; } config[] = {
        {0x34, UINT32_MAX}, {0x38, UINT32_MAX}, {0x3c, UINT32_MAX}, {0x24, 1},
        {0x1a20, UINT32_MAX}, {0x1a24, UINT32_MAX}, {0x1a30, 1},
        {0x1a08, 0x3ffffff}, {0x1a34, 0}, {0x1adc, 0},
        {0x1c0c, 0xffff}, {0x1c10, 0xffff}, {0x1c14, 0}, {0x1c18, 0},
        {0x1c28, 0}, {0x1c2c, 0}, {0x1c30, 0}, {0x1c34, 1},
        {0x1c38, 0}, {0x1c3c, 1}, {0x1c60, 0}, {0x1c64, 0xf},
        {0x1c78, 11u << 8}, {0x1a18, 1u << 4}, {0x1a1c, 0},
        {0x28, 1u << 4}, {0x2c, 1}, {0x30, 0}
    };
    for (unsigned i=0;i<sizeof(config)/sizeof(config[0]);i++)
        if (!io->put(io->context,config[i].reg,config[i].value,false)) goto fail;
    if (!io->put(io->context,0x1c04,(uint32_t)address,false) ||
        !io->put(io->context,0x1c08,frame_inc,true) ||
        !io->put(io->context,0x1c00,0x10001,true) ||
        !io->put(io->context,0x20,1,false)) goto fail;
    return true;
fail:
    rcam_ife_stop(io);
    return false;
}
static inline bool rcam_dphy_rate_supported(uint64_t bits_per_lane)
{
    /* get_clk_voting_dynamic(): rate/8+1 must be below the chosen 400MHz RX clock. */
    return bits_per_lane && bits_per_lane/8+1 < 400000000ull;
}
static inline bool rcam_phy_start(const struct rcam_io *io, unsigned lanes,
    uint32_t assign, unsigned settle)
{
    unsigned used=0;
    if (lanes<1 || lanes>4 || !settle || settle>255) return false;
    for (unsigned i=0;i<lanes;i++) {
        unsigned lane=(assign>>(4*i))&15;
        if (lane>3 || (used&(1u<<lane))) return false;
        used|=1u<<lane;
    }
    /* Logical D-PHY lanes 0,1,2,3 occupy hardware positions 0,2,3,4;
     * the clock occupies position1 (base0x700), as cam_csiphy_core translates it. */
    /* The vendor non-combo D-PHY table enables/configures all five positions. */
    unsigned enabled=0xd5;
    const struct {uint32_t reg,value;} common[]={{0x800,1},{0x800,0},
        {0x814,enabled},{0x818,1},{0x81c,0x5a},{0x824,0x72}};
    for(unsigned i=0;i<sizeof(common)/sizeof(common[0]);i++) {
        if(!io->put(io->context,common[i].reg,common[i].value,common[i].reg!=0x800))goto fail;
        if(i==0)io->delay(io->context,2);
    }
    for(unsigned slot=0;slot<5;slot++) {
        bool clock=slot==1;
        uint32_t base=clock?0x700:(slot?slot-1:0)*0x200;
        const struct {uint32_t reg,value;} lane[]={
            {0x30,0},{0x24,0},{0x00,clock?0x80:0x91},
            {0x38,clock?0x1f:0xfe},{0x2c,1},{0x34,0xf},{0x10,0x52},
            {0x1c,0xa},{0x14,0x60},{0x3c,0xb8},{0x04,0xc},{0x20,0},{0x08,settle}};
        if(clock && (!io->put(io->context,base+0x28,4,true)||
            !io->put(io->context,base+0xc,0xff,true)))goto fail;
        for(unsigned i=0;i<sizeof(lane)/sizeof(lane[0]);i++)
            if(!io->put(io->context,base+lane[i].reg,lane[i].value,true))goto fail;
        if(!io->put(io->context,0x800,2,true))goto fail;
    }
    static const uint8_t irq[]={0xff,0xff,0xfb,0xff,0x7f,0xff,0xff,0xef,0xff,0xff,0xff};
    for(unsigned i=0;i<sizeof(irq);i++) {
        if(!io->put(io->context,0x82c+4*i,irq[i],true) ||
            !io->put(io->context,0x858+4*i,0xff,false))goto fail;
    }
    if(!io->put(io->context,0x828,1,false)||!io->put(io->context,0x828,0,false))goto fail;
    return true;
fail:
    (void)io->put(io->context,0x814,0,false);
    (void)io->put(io->context,0x818,0,false);
    return false;
}
#endif
