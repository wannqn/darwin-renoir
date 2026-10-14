#!/usr/bin/env python3
"""Check actual board/GMU/Mesa parameters and firmware isolation without MMIO."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'xnu/files/bsd/dev/redwood_adreno.c').read_text()
params = source[source.index('bool\nredwood_gpu_parameter'):source.index('/* Addresses for a buffer')]
probe = source[source.index('static bool\nstart_by_itself'):source.index('/*\n * Called while the system starts')]
program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "redwood_adreno_profile.h"
static const struct adreno_board_profile *gpu_profile;
static uint32_t speed_bin=105, core_khz=285000;
#define GPU_CHIP_ID ((uint64_t)gpu_profile->chip_id)
#define REDWOOD_SOC_BASE 0x400000
static uint64_t mach_absolute_time(void) { return 123; }
static bool image_asked_quietly;
static const char *provided_directory;
static unsigned provided_files, requests;
static uint64_t soc_base=REDWOOD_SOC_BASE;
static uint64_t pe_arm_get_soc_base_phys(void) { return soc_base; }
static const uint8_t *image_file(const char *dir, const char *name, uint64_t *size) {
    static const char *files[]={"a660_gmu.bin","a660_sqe.fw","a660_zap.mdt","a660_zap.b02"};
    requests++;*size=100;
    assert(!strcmp(dir,gpu_profile->firmware_directory));
    for(unsigned i=0;i<4;i++) if(!strcmp(name,files[i]))
        return provided_directory && !strcmp(dir,provided_directory) && (provided_files&(1<<i)) ? (const uint8_t *)"fw" : NULL;
    assert(0);return NULL;
}
''' + params + probe + r'''
int main(void) {
    uint64_t v;
    assert(!adreno_profile_for_board(NULL));assert(!adreno_profile_for_board("qemu-virt"));
    assert(!adreno_profile_for_board("renoirX"));assert(!redwood_gpu_parameter(2,&v));
    gpu_profile=adreno_profile_for_board("redwood");
    assert(adreno642_gmu_chip_id(gpu_profile->chip_id)==0x06035000);
    assert(redwood_gpu_parameter(2,&v) && v==512*1024);
    assert(redwood_gpu_parameter(3,&v) && v==((105ull<<32)|0x06030500));
    assert(gpu_profile->speeds[gpu_profile->default_speed].khz==550000);
    assert(gpu_profile->primitive_fifo==0x00200000);
    assert(gpu_profile->gcc_debug_gpucc==0x146);
    gpu_profile=adreno_profile_for_board("renoir");
    assert(adreno642_gmu_chip_id(gpu_profile->chip_id)==0x16060000);
    assert(redwood_gpu_parameter(2,&v) && v==1536*1024);
    assert(redwood_gpu_parameter(3,&v) && v==((105ull<<32)|0x06060010));
    assert(redwood_gpu_parameter(4,&v) && v==285000000);
    assert(redwood_gpu_parameter(0x10,&v) && v==14); /* LPDDR4X override, not DTS's default 15 */
    assert(gpu_profile->speeds[gpu_profile->default_speed].khz==285000);
    assert(gpu_profile->speed_count==2 && gpu_profile->speeds[1].level==64);
    assert(gpu_profile->primitive_fifo==0x00300000);
    assert(gpu_profile->gcc_debug_gpucc==0x13c);
    provided_directory="fw";provided_files=15;assert(!start_by_itself()); /* never redwood's firmware */
    provided_directory="fw-renoir";provided_files=7;assert(!start_by_itself());
    provided_files=15;assert(start_by_itself() && !image_asked_quietly);
    soc_base=0;requests=0;assert(!start_by_itself() && requests==0);
    puts("Adreno profiles: A642/A642L GMU IDs, GMEM, OPP, Mesa params and firmware isolation passed");
}
'''
with tempfile.TemporaryDirectory(prefix='adreno-profile-') as tmp:
    tmp = Path(tmp)
    c = tmp / 'test.c'
    c.write_text(program)
    subprocess.run(['clang', '-Wall', '-Werror', '-fsanitize=address,undefined',
                    '-I', str(ROOT / 'xnu/files/bsd/dev'), str(c), '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True)
    src, dest = tmp / 'fw-gpu', tmp / 'root'
    (src / 'renoir').mkdir(parents=True)
    (src / 'a660_gmu.bin').write_bytes(b'redwood')
    (src / 'renoir/a660_gmu.bin').write_bytes(b'renoir')
    subprocess.run(['bash', str(ROOT / 'userland/pack-gpu-firmware.sh'), str(src), str(dest)], check=True)
    assert (dest / 'fw/a660_gmu.bin').read_bytes() == b'redwood'
    assert (dest / 'fw-renoir/a660_gmu.bin').read_bytes() == b'renoir'
    print('GPU firmware packaging: board directories remain separate')
