#!/usr/bin/env python3
"""Compile and exercise the actual exported kernel injection parser."""
from pathlib import Path
import subprocess, tempfile
r = Path(__file__).resolve().parents[1]
patch = (r / "xnu/renoir.patch").read_text()
added = "\n".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
start = added.index("static bool\nexec_inject_env(")
parser = added[start:added.index("\n}", start) + 2]
code = r'''#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
#define EXECUTABLE_KEY "executable_path="
struct component { const char *cn_nameptr; size_t cn_namelen; };
struct nameidata { struct component ni_cnd; };
struct image_params { struct nameidata *ip_ndp; char *ip_strings; };
static char exec_inject_conf[512];
''' + parser + r'''
static void check(const char *path, const char *name, const char *expected) {
 char saved[512], env[300];
 snprintf(saved, sizeof(saved), "%s%s", EXECUTABLE_KEY, path);
 struct nameidata nd = {{ name, strlen(name) }};
 struct image_params p = { &nd, saved };
 bool found = exec_inject_env(&p, env, sizeof(env));
 assert(found == (expected != NULL));
 if (expected) assert(strcmp(env, expected) == 0);
}
int main(void) {
 strcpy(exec_inject_conf, "/sb SpringBoard;/clock @apps;/bb backboardd");
 check("/System/Library/CoreServices/SpringBoard.app/SpringBoard", "SpringBoard", "DYLD_INSERT_LIBRARIES=/sb");
 check("/Applications/Preferences.app/Preferences", "Preferences", "DYLD_INSERT_LIBRARIES=/clock");
 check("/Applications/Feedback Assistant.app/Feedback Assistant", "Feedback Assistant", "DYLD_INSERT_LIBRARIES=/clock");
 check("/private/var/containers/Bundle/Application/123/App.app/App", "App", "DYLD_INSERT_LIBRARIES=/clock");
 check("/var/containers/Bundle/Application/123/App.app/App", "App", "DYLD_INSERT_LIBRARIES=/clock");
 check("/usr/libexec/backboardd", "backboardd", "DYLD_INSERT_LIBRARIES=/bb");
 check("/usr/libexec/wifid", "wifid", NULL);
 check("/ApplicationsWrong/App", "App", NULL);
 check("/tmp/Applications/Fake.app/Fake", "Fake", NULL);
 check("/var/containers/Bundle/ApplicationWrong/App", "App", NULL);
 strcpy(exec_inject_conf, "/clock @appsWrong");
 check("/Applications/App.app/App", "App", NULL);
 puts("statusbar exec: app paths, spaces, daemon isolation and existing groups passed");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p = Path(tmp)
 (p / "test.c").write_text(code)
 subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", str(p / "test.c"), "-o", str(p / "test")], check=True)
 subprocess.run([str(p / "test")], check=True)

# Board selection comes from the physical DT, never the spoofed iPhone identity.
source = (r / "userland/src/statusbar.c").read_text()
a = source.index("static int\nis_renoir(")
board = source[a:source.index("\n}", a) + 2]
code = r'''#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef long CFIndex;
typedef unsigned char UInt8;
typedef const void *CFTypeRef;
typedef const void *CFDataRef;
typedef int io_registry_entry_t;
#define MACH_PORT_NULL 0
#define CFSTR(x) (x)
#define kCFAllocatorDefault NULL
static const char *data;
static long length;
static int present=1, is_data=1;
static int IORegistryEntryFromPath(int port, const char *path) {
 assert(port==0 && strcmp(path,"IODeviceTree:/chosen")==0);return present;
}
static CFTypeRef IORegistryEntryCreateCFProperty(int chosen, const char *key, const void *allocator, int options) {
 (void)allocator; assert(chosen==1 && options==0 && strcmp(key,"darwin-board")==0);return data;
}
static int CFGetTypeID(CFTypeRef obj) {(void)obj;return is_data;}
static int CFDataGetTypeID(void) {return 1;}
static CFIndex CFDataGetLength(CFDataRef obj) {(void)obj;return length;}
static const UInt8 *CFDataGetBytePtr(CFDataRef obj) {return obj;}
static void CFRelease(CFTypeRef obj) {(void)obj;}
static void IOObjectRelease(int obj) {(void)obj;}
''' + board + r'''
int main(void) {
 data="renoir"; length=7; assert(is_renoir());
 length=6; assert(is_renoir());
 length=5; assert(!is_renoir());
 data="renoirX";length=7;assert(!is_renoir());
 data="renoir\0X";length=8;assert(!is_renoir());
 data="redwood";length=8;assert(!is_renoir());
 data="qemu";length=5;assert(!is_renoir());
 data="renoir";length=7;is_data=0;assert(!is_renoir());
 is_data=1;present=0;assert(!is_renoir());
 present=1;data=NULL;assert(!is_renoir());
 puts("statusbar board: Renoir only, exact lengths, wrong type and missing DT passed");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p = Path(tmp)
 (p / "test.c").write_text(code)
 subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", str(p / "test.c"), "-o", str(p / "test")], check=True)
 subprocess.run([str(p / "test")], check=True)
