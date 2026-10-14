/* Minimal static PID1 for hardware probes. No dyld, libc or disk writes.
 * The Darwin executable entry stack must be aligned before entering C;
 * the kernel's argc/argv layout is not a C function-call stack frame.
 */
__asm__(".text\n.p2align 2\n.globl _start\n_start:\n"
        "mov x9, sp\nand sp, x9, #0xfffffffffffffff0\n"
        "bl _probe_main\n1: yield\nb 1b\n");

static long
syscall3(long num, long a, long b, long c)
{
	register long x16 __asm__("x16") = num;
	register long x0 __asm__("x0") = a;
	register long x1 __asm__("x1") = b;
	register long x2 __asm__("x2") = c;
	__asm__ volatile("svc #0x80" : "+r"(x0) : "r"(x16), "r"(x1), "r"(x2) : "memory", "cc");
	return x0;
}

void
probe_main(void)
{
	static const char message[] = "Hardware probe: PID1 running with aligned stack.\n";
	long fd = syscall3(5, (long)"/dev/console", 2, 0);
	if (fd >= 0) { syscall3(4, fd, (long)message, sizeof(message)-1); }
	for (;;) { __asm__ volatile("yield"); }
}
