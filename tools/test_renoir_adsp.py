#!/usr/bin/env python3
"""Run the real ADSP MDT validator with Renoir carveout bounds and malformed metadata."""
from pathlib import Path
import tempfile, subprocess
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/redwood_adsp.c').read_text()
a=s.index('#define MDT_HASH');b=s.index('/* The image',a)
layout=s[a:b]
a=s.index('static bool\nstep_firmware(');b=s.index('\nstatic bool',a+1)
helper=s[a:b]
code=r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
#define PAGE_SIZE 16384
#define ADSP_MEMORY 0x86700000u
static uint32_t adsp_memory_size=0x03000000;
#define ADSP_MEMORY_SIZE adsp_memory_size
static unsigned step=2;
static bool from_root;
static uint8_t header[52+3*32+32],data[16];
static unsigned scenario;
static void announce(const char *s){(void)s;}
"""+layout+r"""
static void image_forget(void){memset(&image,0,sizeof(image));}
static const uint8_t *image_file(const char *name,uint64_t *size){
 if(!strcmp(name,"adsp.mdt")){*size=scenario==1 ? 1 : sizeof(header);return header;}
 if(scenario==4)return NULL;
 *size=scenario==5 ? 15 : sizeof(data);return data;
}
"""+helper+r"""
int main(void){
 memcpy(header,"\177ELF\1",5);header[44]=3;
 struct elf_segment hash={.type=1,.file_size=32,.flags=2u<<24};
 struct elf_segment load={.type=1,.paddr=ADSP_MEMORY,.file_size=16,.memory_size=0x1000};
 memcpy(header+52+32,&hash,sizeof(hash));memcpy(header+52+64,&load,sizeof(load));
 assert(step_firmware() && image.size==0x1000);
 scenario=1;assert(!step_firmware()); /* truncated header must not read beyond it */
 scenario=2;load.paddr=ADSP_MEMORY+0x03000000-0x800;
 memcpy(header+52+64,&load,sizeof(load));assert(!step_firmware()); /* past Renoir carveout */
 adsp_memory_size=0x04000000; /* Redwood larger carveout still accepts bounds, but requires lowest base */
 assert(!step_firmware());
 adsp_memory_size=0x03000000;load.paddr=ADSP_MEMORY;load.file_size=0x1001;
 memcpy(header+52+64,&load,sizeof(load));assert(!step_firmware());
 load.file_size=16;memcpy(header+52+64,&load,sizeof(load));
 scenario=4;assert(!step_firmware());scenario=5;assert(!step_firmware());
 scenario=0;assert(step_firmware());
 return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='renoir-adsp-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Wall','-Werror','-Wno-format','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('ADSP validator: Renoir48MiB bounds, short MDT, oversized/missing/truncated segments passed')
