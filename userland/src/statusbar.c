/* Renoir's top-left hole punch: use UIKit's native leading-region metric.
 * iOS 16.5 / 20F66, iPhone10,3 userland. No view frames, transforms, timers,
 * visibility or text widths are changed; recreated bars consult the same metric.
 * Compiled into libredwood-sb and the small library injected into applications.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <objc/runtime.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>

extern const void *_dyld_get_shared_cache_range(size_t *);
static double (*original_offset)(id, SEL);
#define RENOIR_CLOCK_SHIFT_POINTS 12.0

static double
leading_offset(id self, SEL cmd)
{
    /* Always start from Apple's metric, never from a previously shifted frame. */
    return original_offset(self, cmd) + RENOIR_CLOCK_SHIFT_POINTS;
}

static int
is_renoir(void)
{
    int match = 0;
    io_registry_entry_t chosen = IORegistryEntryFromPath(MACH_PORT_NULL, "IODeviceTree:/chosen");
    if (chosen) {
        CFTypeRef board = IORegistryEntryCreateCFProperty(chosen, CFSTR("darwin-board"), kCFAllocatorDefault, 0);
        if (board && CFGetTypeID(board) == CFDataGetTypeID()) {
            CFIndex n = CFDataGetLength((CFDataRef)board);
            const UInt8 *p = CFDataGetBytePtr((CFDataRef)board);
            match = (n == 6 || (n == 7 && p[6] == 0)) && memcmp(p, "renoir", 6) == 0;
        }
        if (board) CFRelease(board);
        IOObjectRelease(chosen);
    }
#ifdef RENOIR_STATUSBAR_TEST
    /* Diagnostic QEMU build only; absent from the normal phone library. */
    match = 1;
#endif
    return match;
}

__attribute__((constructor))
static void
renoir_statusbar_init(void)
{
    if (original_offset || !is_renoir()) return;
    Class cls = objc_getClass("_UIStatusBarVisualProvider_Split1125");
    SEL sel = sel_registerName("leadingCenteringOffset");
    Method method = cls ? class_getClassMethod(cls, sel) : NULL;
    size_t size = 0;
    const void *cache = _dyld_get_shared_cache_range(&size);
    uintptr_t expected = (uintptr_t)cache - 0x180000000ull + 0x189225384ull;
    /* Refuse another iOS ABI/cache instead of applying a guessed hook. */
    if (!method || !cache || strcmp(method_getTypeEncoding(method), "d16@0:8") ||
        (uintptr_t)method_getImplementation(method) != expected) return;
    original_offset = (double (*)(id, SEL))method_getImplementation(method);
    method_setImplementation(method, (IMP)leading_offset);
    int fd = open("/dev/console", O_WRONLY | O_NOCTTY);
    if (fd >= 0) {
        dprintf(fd, "renoir: statusbar %s[%d] leading metric +%.0f pt\n",
            getprogname(), getpid(), RENOIR_CLOCK_SHIFT_POINTS);
        close(fd);
    }
}
