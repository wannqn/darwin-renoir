#!/usr/bin/env python3
"""Exercise the actual renoir survey against fake MMIO, never PCIe hardware."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
src = (root / 'xnu/files/bsd/dev/redwood_wifi.c').read_text()
start = src.index('static bool\nrenoir_pmic_read(')
end = src.index('\nvoid\nredwood_wifi_init(void)', start)
entry = src[end:]
assert entry.index('redwood_board_is("renoir")') < entry.index('redwood_qmi_set_transport(')
assert entry.index('!redwood_board_is("redwood")') < entry.index('kernel_thread_start(whole_thread')
survey = src[start:end]
smmu_start=survey.index('/* DT iommu-map:')
smmu_end=survey.index('static void\nrenoir_wifi_init(void)',smmu_start)
survey=survey[:smmu_start]+survey[smmu_end:]
program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uintptr_t vm_offset_t;
static uint32_t gcc[0x70000/4], tlmm[0x61000/4], parf[0x4000/4];
static uint32_t core[0x1100/4], observer[0x10000/4];
static unsigned probe, mappings, writes, parf_reads, reads;
static bool whole;
static vm_offset_t ml_io_map(vm_offset_t pa, vm_offset_t size) {
    mappings++; assert(size <= 0x70000); /* large early allocations panic in XNU */
    if (pa==0x100000) { assert(size==sizeof(gcc)); return (uintptr_t)gcc; }
    if (pa==0xf100000) { assert(size==sizeof(tlmm)); return (uintptr_t)tlmm; }
    if (pa==0xc440000) { assert(size==sizeof(core)); return (uintptr_t)core; }
    if (pa==0xe600000) { assert(size==sizeof(observer)); return (uintptr_t)observer; }
    assert(pa==0x1c00000 && size==sizeof(parf)); /* no DBI, endpoint BAR or DMA */
    return (uintptr_t)parf;
}
static bool PE_parse_boot_argn(const char *key, void *out, unsigned size) {
    assert(!strcmp(key,"wifi_probe") && size==4); memcpy(out,&probe,4); return true;
}
static uint32_t rd(uintptr_t a) {
    if (a >= (uintptr_t)parf && a < (uintptr_t)(parf+sizeof(parf)/4)) { parf_reads++; }
    return *(uint32_t *)a;
}
static void wr(uintptr_t a, uint32_t v) {
    if (a >= (uintptr_t)observer && a < (uintptr_t)(observer+sizeof(observer)/4)) {
        assert(a == (uintptr_t)&observer[3*0x80/4]); /* only the mapped channel */
        assert((v & (0x1fu<<27)) == (1u<<27)); /* SPMI READ, never WRITE */
        unsigned reg=(v>>4)&255;
        assert(reg==4 || reg==0x40 || reg==0x10);
        reads++;
        observer[(3*0x80+8)/4]=1;
        observer[(3*0x80+0x18)/4]=reg==4 ? 0xa03 : reg==0x40 ? 0x7060504 : 0x80;
        observer[(3*0x80+0x1c)/4]=0xb0a0908;
        return;
    }
    writes++;
    if (a==(uintptr_t)&gcc[0x6b004/4]) {
        v = (v & ~0x80000000u) | ((v & 1) ? 0 : 0x80000000u);
    } else { assert(a==(uintptr_t)&gcc[0x52008/4]); }
    *(uint32_t *)a=v;
}
static void sleep_ms(unsigned ms) { (void)ms; }
static void sleep_us(unsigned us) { (void)us; }
static void say(const char *format, ...) { (void)format; }
static bool renoir_pcie_ldo(const char *name, uint32_t mv, bool on) {
    (void)name; (void)mv; (void)on; assert(0); return false;
}
static bool renoir_pcie_phy_probe(vm_offset_t g, vm_offset_t t, bool dbi) {
    (void)g; (void)t; (void)dbi; assert(0); return false;
}
static void renoir_wifi_vote_survey(void) { assert(0); }
static void renoir_wifi_smmu_survey(void) { assert(0); }
static void renoir_wifi_smmu_probe(void) { assert(0); }
struct renoir_radio_votes { unsigned unused; };
static bool renoir_radio_power(struct renoir_radio_votes *v, bool on) { (void)v;(void)on;assert(0);return false; }
''' + survey.replace('__asm__ volatile("dsb sy" ::: "memory");', '(void)0;') + r'''
int main(void) {
    for(probe=0;probe<=4;probe++) {
        memset(gcc,0,sizeof(gcc)); memset(tlmm,0,sizeof(tlmm));
        gcc[0x6b004/4]=0x22f001; gcc[0x52008/4]=0x83c8000;
        mappings=writes=parf_reads=0;
        renoir_wifi_init();
        assert(gcc[0x6b004/4]==0x22f001 && gcc[0x52008/4]==0x83c8000);
        assert(probe ? mappings>=2 : mappings==0);
        assert(probe<2 ? writes==0 : writes>0);
        assert(probe==4 ? parf_reads==2 : parf_reads==0);
        for(unsigned i=0;i<sizeof(tlmm)/4;i++) { assert(tlmm[i]==0); }
    }
    probe=8; core[0]=0x50000000; core[(0x900+4*3)/4]=0x114<<8;
    /* Zero FEATURES uses the same bounded 512-channel fallback as buttons. */
    renoir_wifi_init(); assert(reads==3);
    uint8_t data[8];
    assert(renoir_pmic_read((uintptr_t)observer,3,0x40,data,8));
    for(unsigned i=0;i<8;i++) { assert(data[i]==i+4); }
    assert(gcc[0x6b004/4]==0x22f001 && gcc[0x52008/4]==0x83c8000);
    puts("Renoir Wi-Fi: board gates, bounded mappings, no endpoint/DMA and host-state restoration passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-wifi-') as tmp:
    p = Path(tmp)
    (p / 'test.c').write_text(program)
    subprocess.run(['clang', '-Wall', '-Wextra', '-Wno-unused-variable',
                    '-fsanitize=address,undefined', str(p / 'test.c'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True)
