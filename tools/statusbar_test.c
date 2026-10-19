/* Diagnostic only. Link UIKit, then run: statusbar_test 24 (forced QEMU
 * build), or statusbar_test 0 (normal library on QEMU/non-Renoir). */
#include <objc/runtime.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
int main(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    Class cls = objc_getClass("_UIStatusBarVisualProvider_Split1125");
    SEL sel = sel_registerName("leadingCenteringOffset");
    Method method = cls ? class_getClassMethod(cls, sel) : NULL;
    if (!method || argc != 2) return 2;
    double (*metric)(id, SEL) = (void *)method_getImplementation(method);
    double before = metric((id)cls, sel), shift = strtod(argv[1], NULL);
    void *handle = dlopen("/redwood/lib/libredwood-statusbar.dylib", RTLD_NOW);
    if (!handle) {printf("CLOCKTEST dlopen: %s\n", dlerror()); return 3;}
    for (unsigned i = 0; i < 10000; i++) {
        metric = (void *)method_getImplementation(method);
        double after = metric((id)cls, sel);
        if (fabs(after - before - shift) > 0.00001) {
            printf("CLOCKTEST FAIL iteration %u before %.6f after %.6f shift %.0f\n", i, before, after, shift);
            return 1;
        }
    }
    printf("CLOCKTEST PASS 10000 native metric calls: %.6f -> %.6f (shift %.0f)\n",
        before, metric((id)cls, sel), shift);
    return 0;
}
