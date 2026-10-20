#!/usr/bin/env python3
"""Run actual first-panic formatter without relying on the console/debugger."""
from pathlib import Path
import subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/osfmk/arm64/loader_return.c').read_text()
a=s.index('void\nloader_note_panic(');b=s.index('\n}',a)+2
code=r"""
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
static char logdata[4096];static size_t used;
#define relaxed 0
static bool cas(bool*p,bool old,bool new,int order){(void)order;if(*p!=old)return false;*p=new;return true;}
#define os_atomic_cmpxchg cas
static void loader_log_putc(char c){assert(used+1<sizeof(logdata));logdata[used++]=c;logdata[used]=0;}
static void loader_log_puts(const char*s){while(*s)loader_log_putc(*s++);}
"""+s[a:b]+r"""
static void emit(const char *format,...){va_list a;va_start(a,format);loader_note_panic(format,&a,0x1234);va_end(a);}
int main(void){
 emit(NULL);assert(!used);
 char text[1500];memset(text,'x',sizeof(text));text[1499]=0;
 emit("failure %d %s",12,text);
 assert(strstr(logdata,"EARLY PANIC: failure 12 ") && strstr(logdata,"panic caller 0x0000000000001234"));
 assert(used<1200);size_t first=used;
 emit("secondary panic");assert(used==first);
 puts("Early panic: null input, va_list formatting, bounded truncation, caller address and first-panic retention passed");
}
"""
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
