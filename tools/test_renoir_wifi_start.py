#!/usr/bin/env python3
"""Run Renoir's actual startup gate without saved credentials or hardware."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'xnu/files/bsd/dev/redwood_wifi.c').read_text()
start = source.index('static void\nrenoir_wifi_begin(void)')
end = source.index('\nstatic void\nrenoir_wifi_stop(void)', start)
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define REDWOOD_SOC_BASE 123
#define KERN_SUCCESS 0
typedef int thread_t;
static bool hardware, firmware, address_ok, thread_ok;
static bool whole, quiet, renoir_session_wanted, renoir_session_running;
static unsigned early, started, released;
static unsigned pe_arm_get_soc_base_phys(void) { return hardware ? 123 : 0; }
static void *image_file_in(const char *dir, const char *name, uint64_t *length) {
 assert(!strcmp(dir,"fw-wifi-renoir"));
 assert(!strcmp(name,"amss20.bin") || !strcmp(name,"bd_k9gl.elf"));
 *length=1; return firmware ? (void *)1 : 0;
}
/* No image_file stub: startup must never require the private network file. */
static bool redwood_wifi_radio_address(uint8_t *out) { (void)out; return address_ok; }
static bool PE_parse_boot_argn(const char *s, void *p, unsigned n) {
 (void)s; (void)p; (void)n; return false;
}
static void tell(const char *s) { (void)s; }
static void redwood_lx_net_early(void) { early++; }
static void renoir_bhi_reserve(uint32_t size) { assert(size==1 && early); }
static void renoir_wifi_thread(void) {}
static int kernel_thread_start(void (*fn)(void), void *p, thread_t *t) {
 assert(fn==renoir_wifi_thread && !p); started++; *t=1; return thread_ok ? 0 : 1;
}
static void thread_deallocate(thread_t t) { assert(t==1); released++; }
''' + source[start:end] + r'''
int main(void) {
 hardware=firmware=address_ok=thread_ok=true;
 renoir_wifi_begin();
 assert(started==1 && early==1 && released==1);
 assert(whole && quiet && renoir_session_wanted && renoir_session_running);
 for (unsigned missing=0; missing<3; missing++) {
  hardware=missing!=0; firmware=missing!=1; address_ok=missing!=2;
  renoir_wifi_begin(); assert(started==1 && early==1);
 }
 hardware=firmware=address_ok=true; thread_ok=false;
 renoir_wifi_begin(); assert(started==2 && released==1);
 assert(!renoir_session_wanted && !renoir_session_running);
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-wifi-start-') as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('Renoir Wi-Fi: credential-free startup, hardware/firmware/MAC gates and thread failure passed')
