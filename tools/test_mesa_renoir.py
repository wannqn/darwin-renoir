#!/usr/bin/env python3
"""Test the patched Mesa generator + its actual C device-ID matcher on the host.
Run with xnu-deps/build/mesa/venv/bin/python3 after tools/mk-mesa.sh.
"""
from contextlib import redirect_stdout
import io
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
mesa = ROOT / 'xnu-deps/build/mesa'
source = mesa / 'mesa-26.2.5/src/freedreno/common'
registers = next(mesa.glob('build-26.2.5-*/src/freedreno/registers/adreno/a6xx.py'))
sys.argv = [str(source / 'freedreno_devices.py'), '-p', str(registers.parent)]
sys.path.insert(0, str(source))  # Mesa26 splits generator types into freedreno_dev_info.py.
with redirect_stdout(io.StringIO()):
    data = runpy.run_path(sys.argv[0])
renoir = next(info for gpu, info in data['s'].gpus.items() if gpu.name == 'FD642')
assert renoir.chip == data['CHIP'].A6XX.value
assert renoir.num_ccu == 3 and renoir.highest_bank_bit == 14
assert (renoir.tile_align_w, renoir.tile_align_h) == (96, 16)
assert (renoir.tile_max_w, renoir.tile_max_h) == (1024, 1024)
assert dict(renoir.magic_raw)[int(data['A6XXRegs'].REG_A6XX_UCHE_CLIENT_PF)] == 0x84
records = ',\n'.join(
    '{{%d, 0x%xull}, "%s", %d}' % (gpu.gpu_id, gpu.chip_id, gpu.name, info.highest_bank_bit)
    for gpu, info in data['s'].gpus.items())
code = (source / 'freedreno_dev_info.c').read_text()
start = code.index('static bool\ndev_id_compare')
matcher = code[start:code.index('const struct fd_dev_info *', start)]
program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
struct fd_dev_id { uint32_t gpu_id; uint64_t chip_id; };
struct rec { struct fd_dev_id id; const char *name; unsigned bank; };
''' + matcher + '\nstatic const struct rec records[] = {\n' + records + r'''
};
static const struct rec *lookup(uint64_t chip) {
    const struct fd_dev_id id={0,chip};
    for(unsigned i=0;i<sizeof(records)/sizeof(records[0]);i++)
        if(dev_id_compare(&records[i].id,&id))return &records[i];
    return NULL;
}
int main(void) {
    const struct rec *r;
    r=lookup(0x006906060010ull);assert(r && !strcmp(r->name,"FD642") && r->bank==14);
    r=lookup(0x000006060010ull);assert(r && !strcmp(r->name,"FD642") && r->bank==14);
    r=lookup(0x006906060000ull);assert(r && !strcmp(r->name,"FD660") && r->bank==16);
    r=lookup(0x006906030500ull);assert(r && r->bank==14);
    assert(!lookup(0xdeadbeefdeadbeefull));
    puts("Mesa: renoir matches FD642 bank 14 before FD660 wildcard; redwood unchanged");
}
'''
with tempfile.TemporaryDirectory(prefix='mesa-renoir-') as tmp:
    c = Path(tmp) / 'test.c'
    c.write_text(program)
    exe = Path(tmp) / 'test'
    subprocess.run(['clang', '-Wall', '-Werror', '-fsanitize=address,undefined',
                    str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
