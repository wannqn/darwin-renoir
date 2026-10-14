#!/usr/bin/env python3
"""Exercise actual FT3658U protocol/events with a scripted SPI peer, ASan and UBSan.
No hardware access. Fixtures follow the OKX SPI and six-byte contact formats.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'xnu/files/bsd/dev/renoir_fts.c').read_text()
protocol = source.split('/* ---- FT3658U application protocol', 1)[1]
protocol = protocol[protocol.index('#include "renoir_fts_protocol.h"'):protocol.index('static void\nfts_reset')]
guard = source[source.index('void\nrenoir_fts_init'):]
probe = source[source.index('static bool\nfts_probe'):source.index('static bool\nfts_bring_up')]
clock_check = source[source.index('static bool\nfts_ahb_clock_ready'):source.index('static uint32_t\nrcg_rate')]
program = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
enum { REDWOOD_TOUCH_DOWN, REDWOOD_TOUCH_MOVE, REDWOOD_TOUCH_UP };
static struct { unsigned kind, id, x, y; } events[100];
static unsigned nevents, attempts, delays, scenario;
static uint8_t reply[62];
static uint8_t chip_high=0x56, chip_low=0x52, work_mode;
static void sleep_ms(unsigned ms) { assert(ms==100); }
static void redwood_touch_post(unsigned kind, unsigned id, unsigned x, unsigned y) {
    assert(nevents < 100);
    events[nevents++] = (typeof(events[0])){kind,id,x,y};
}
static void sleep_us(unsigned us) { assert(us == 150); delays++; }
/* Independent bitwise CRC implementation for the emulated device. */
static uint16_t peer_crc(const uint8_t *p, unsigned n) {
    unsigned c=0xffff;
    while(n--) { unsigned b=*p++; for(unsigned i=0;i<8;i++,b>>=1) {
        unsigned low=(c ^ b)&1; c>>=1; if(low)c^=0x8408;
    }} return c;
}
static bool geni_transfer(const uint8_t *tx, uint8_t *rx, uint32_t n) {
    attempts++;
    unsigned count=tx[2]*256+tx[3];
    assert(tx[1]==0xa0 && n==count+9);
    assert((tx[0]==1 && count==62) || (tx[0]!=1 && count==1));
    for(unsigned i=4;i<n;i++)assert(tx[i]==0);
    if(scenario==1 && attempts==1) return false;
    if(tx[0]==1) memcpy(rx+7, reply, count);
    else if(tx[0]==0xa3)rx[7]=chip_high;
    else if(tx[0]==0x9f)rx[7]=chip_low;
    else if(tx[0]==0)rx[7]=work_mode;
    else { assert(tx[0]==0xa6);rx[7]=0x21; }
    uint16_t c=peer_crc(rx+7,count);
    rx[7+count]=c; rx[8+count]=c>>8;
    if(scenario==1 && attempts==2) rx[3]=0xa0;
    if(scenario==2) rx[8+count]^=1;
    return true;
}
''' + '\n#define CLOCK_OFF (1u << 31)\n' + clock_check + protocol + probe + r'''
static void blank(unsigned count) { memset(reply,0xff,sizeof(reply));reply[0]=0;reply[1]=count; }
static void point(unsigned slot,unsigned id,unsigned event,unsigned x,unsigned y) {
    uint8_t *p=reply+2+slot*6;
    p[0]=(event<<6)|(x>>8);p[1]=x;p[2]=(id<<4)|(y>>8);p[3]=y;p[4]=20;p[5]=0x90;
}
typedef void *thread_t;
enum { KERN_SUCCESS = 0 };
static bool boot_enabled, is_renoir;
static unsigned threads;
static void fts_thread(void) { assert(0); }
static bool PE_parse_boot_argn(const char *name, void *out, unsigned size) {
    if (!strcmp(name,"touchscreen")) { *(uint32_t *)out=boot_enabled;return true; }
    return false;
}
static bool redwood_board_is(const char *name) { assert(!strcmp(name,"renoir"));return is_renoir; }
static int kernel_thread_start(void (*entry)(void), void *arg, thread_t *out) {
    assert(entry==fts_thread);threads++;*out=0;return 0;
}
static void thread_deallocate(thread_t thread) {}
''' + guard + r'''
int main(void) {
    assert(fts_crc((const uint8_t *)"123456789",9)==0x6f91);
    assert(fts_ahb_clock_ready(0x8000000a)); /* actual renoir S_AHB idle/HWCG status */
    assert(fts_ahb_clock_ready(0));assert(!fts_ahb_clock_ready(0x80000000));
    struct fts_frame f;
    uint8_t readback[62];
    blank(2);point(0,2,0,540,1200);point(1,7,2,1080,2400);
    assert(fts_read(1,readback,62) && attempts==1 && delays==1);
    assert(fts_decode(readback,62,&f) && f.active==((1<<2)|(1<<7)));
    fts_report(&f);assert(nevents==2 && events[0].kind==REDWOOD_TOUCH_DOWN);
    assert(events[0].id==2 && events[0].x==32767 && events[1].x==65535 && events[1].y==65535);
    fts_report(&f);assert(nevents==2); /* identical report produces no fake movement */
    blank(1);point(0,2,2,100,300);point(1,7,1,0,0);
    assert(fts_decode(reply,62,&f));fts_report(&f);
    assert(nevents==4 && events[2].kind==REDWOOD_TOUCH_MOVE && events[3].kind==REDWOOD_TOUCH_UP);
    blank(0);assert(fts_decode(reply,62,&f));fts_report(&f);
    assert(nevents==5 && events[4].kind==REDWOOD_TOUCH_UP);
    blank(10);for(unsigned i=0;i<10;i++)point(i,i,0,i*100,i*200);
    assert(fts_decode(reply,62,&f) && f.active==1023);
    fts_report(&f);assert(nevents==15);fts_release();assert(nevents==25);
    flip=3;blank(1);point(0,0,0,0,0);assert(fts_decode(reply,62,&f));fts_report(&f);
    assert(events[25].x==65535 && events[25].y==65535);fts_release();flip=0;
    /* Invalid data must not partially overwrite the decoded frame or generate events. */
    struct fts_frame saved=f;
    point(1,0,0,10,10);assert(!fts_decode(reply,62,&f) && !memcmp(&f,&saved,sizeof(f)));
    blank(1);point(0,0,3,1,1);assert(!fts_decode(reply,62,&f));
    blank(1);point(0,0,0,1081,1);assert(!fts_decode(reply,62,&f));
    blank(0);point(0,0,0,1,1);assert(!fts_decode(reply,62,&f));
    blank(11);assert(!fts_decode(reply,62,&f));
    assert(!fts_decode(reply,61,&f));
    memset(reply,0xff,62);assert(!fts_decode(reply,62,&f));
    assert(fts_report_empty(reply,62));reply[5]=0;assert(!fts_report_empty(reply,62));
    blank(1);point(0,9,0,1080,2400);
    attempts=delays=0;scenario=1;assert(fts_read(1,readback,62));
    assert(attempts==3 && delays==3);
    attempts=delays=0;scenario=2;memset(readback,0x55,62);
    assert(!fts_read(1,readback,62) && attempts==3 && delays==3);
    for(unsigned i=0;i<62;i++)assert(readback[i]==0x55);
    assert(!fts_read(1,readback,0) && !fts_read(1,readback,63));
    scenario=0;assert(fts_probe());
    chip_low=0xb2;assert(!fts_probe()); /* bootloader/unknown chip is not an input source */
    chip_low=0x52;work_mode=0x40;assert(!fts_probe()); /* factory mode */
    work_mode=0;
    boot_enabled=false;is_renoir=true;renoir_fts_init();assert(threads==0);
    boot_enabled=true;is_renoir=false;renoir_fts_init();assert(threads==0);
    is_renoir=true;renoir_fts_init();assert(threads==1);
    /* Fuzz the bounded decoder with truncated and malformed packets under ASan/UBSan. */
    uint32_t seed=12345;
    for(unsigned j=0;j<10000;j++) {
        for(unsigned i=0;i<62;i++) { seed=seed*1664525+1013904223;reply[i]=seed>>24; }
        (void)fts_decode(reply,j%63,&f);
    }
    puts("FT3658U: SPI CRC/retries, packet validation, ten contacts, down/move/up, flip and board guards passed");
}
'''
with tempfile.TemporaryDirectory(prefix='renoir-fts-') as tmp:
    c = Path(tmp) / 'test.c'
    c.write_text(program)
    exe = Path(tmp) / 'test'
    subprocess.run(['clang', '-std=gnu11', '-Wall', '-Werror', '-Wno-unused-function',
                    '-fsanitize=address,undefined', '-g',
                    '-I', str(ROOT / 'xnu/files/bsd/dev'), str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
