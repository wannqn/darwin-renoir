#!/usr/bin/env python3
"""Exercise the camera driver's actual supply journal and power-step dispatch."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / 'xnu/files/bsd/dev/redwood_camera.c').read_text()

def function(name):
    start = source.rfind('static ', 0, source.index('\n' + name + '('))
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

journal = source[source.index('static struct {', source.index('/* Each GPIO supply')):source.index('static bool\ngpio_supplies_changed')]
code = r'''#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
enum { SUPPLY_NONE, SUPPLY_LDO, SUPPLY_GPIO };
struct supply { uint8_t kind, ldo; uint16_t mv, gpio, ramp_us; };
struct ctab_entry { uint16_t address, data; uint8_t ab,db,op,z; uint32_t delay_us; };
struct { struct supply vana, vdig, vio, vaf; } test_hw, *hw = &test_hw;
static uint32_t mmio[1024];
static int writes, fail_write, ldo_n, ldo_mv;
static bool broken, camera_renoir;
#define GPIO_CFG(n) (2*(n))
#define GPIO_IO(n) (2*(n)+1)
#define CFG_OUTPUT 512
#define CFG_DRIVE_MA(n) 0
static uint32_t rd(unsigned p) { return mmio[p]; }
static void wr(unsigned p,uint32_t v) { if (++writes!=fail_write) mmio[p]=v; }
static void give_up(const char *s) { (void)s; broken=true; }
static int say(const char *s,...) { (void)s; return 0; }
static void spin_us(unsigned n) { (void)n; }
static bool ldo_on(unsigned n,unsigned mv) { ldo_n=n;ldo_mv=mv;return true; }
static void ldo_off(unsigned n) { ldo_n=-(int)n; }
static bool reset_driven;
static void reset_pin(bool b) { (void)b; }
static bool gdsc_on(void) { return true; }
static bool mclk_on(unsigned n) { return n==19200; }
static void mclk_off(void) {}
static void sensor_delay(unsigned n) { (void)n; }
'''
code += journal + '\n' + '\n'.join(function(n) for n in ['pin_config','gpio_supplies_changed','supply_on','supply_off','power_step'])
code += r'''
int main(void) {
    hw->vana=(struct supply){SUPPLY_GPIO,0,2800,176,135};
    hw->vdig=(struct supply){SUPPLY_GPIO,0,1050,177,135};
    hw->vaf=(struct supply){SUPPLY_LDO,3,2800,0,0};
    mmio[352]=0x17;mmio[353]=0;mmio[354]=0x29;mmio[355]=2;
    assert(supply_on(&hw->vana)); assert(supply_on(&hw->vdig));
    assert(gpio_supplies_changed());
    supply_off(&hw->vana); /* free an earlier slot while another rail stays on */
    assert(mmio[352]==0x17 && mmio[353]==0);
    int before=writes; assert(supply_on(&hw->vdig)); assert(writes==before);
    supply_off(&hw->vdig);
    assert(mmio[354]==0x29 && mmio[355]==2); /* previously-on rail stays on */
    assert(!gpio_supplies_changed());
    for(int failure=1;failure<=2;failure++) {
        writes=0;fail_write=failure;broken=false;
        mmio[352]=0x17;mmio[353]=0;
        assert(!supply_on(&hw->vana));assert(broken);
        fail_write=0;supply_off(&hw->vana);
        assert(mmio[352]==0x17 && mmio[353]==0);
        assert(!gpio_supplies_changed());
    }
    camera_renoir=true;
    mmio[352]=0x8800;mmio[353]=0;
    assert(supply_on(&hw->vana)); assert(mmio[352]==0x9a00);
    supply_off(&hw->vana); assert(mmio[352]==0x8800 && mmio[353]==0);
    mmio[352]=0x8000;
    assert(supply_on(&hw->vana)); assert(mmio[352]==0x8200);
    supply_off(&hw->vana); assert(mmio[352]==0x8000);
    camera_renoir=false;
    struct ctab_entry e={.address=4,.data=1};
    assert(power_step(&e,true));assert(ldo_n==3 && ldo_mv==2800);
    e.data=0;assert(power_step(&e,false));assert(ldo_n==-3);
    e.address=9;assert(!power_step(&e,true));
    puts("Camera power: two GPIO rails, per-rail restoration, partial failures, VAF and unsupported steps passed");
}
'''
with tempfile.TemporaryDirectory() as d:
    path=Path(d);(path/'test.c').write_text(code)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(path/'test.c'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
