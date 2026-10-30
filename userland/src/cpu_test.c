/*
 * How many processors the kernel has, and whether they really work at the same time: a fixed
 * amount of arithmetic on one thread, then the same on each of as many threads as there are
 * processors (two at least), and how much processor time the threads were given between
 * them while that took: with one processor never more than the time that passed, with
 * several of them free several times as much.
 *
 * usage: cpu_test [SECONDS]    without an argument only the numbers; with one, wait that long
 *                             (for a moment when the system is quiet) and then do the work
 */
#include <mach/mach_time.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <sys/sysctl.h>
#include <unistd.h>

#define ROUNDS  60000000ULL
#define MOST    16

static int
number(const char *name)
{
	int value = -1;
	size_t size = sizeof(value);

	sysctlbyname(name, &value, &size, NULL, 0);
	return value;
}

static uint64_t
milliseconds(void)
{
	static mach_timebase_info_data_t timebase;

	if (timebase.denom == 0) {
		mach_timebase_info(&timebase);
	}
	return mach_absolute_time() * timebase.numer / timebase.denom / 1000000;
}

/* The processor time this process has used so far, in milliseconds. */
static uint64_t
used(void)
{
	struct rusage usage;

	getrusage(RUSAGE_SELF, &usage);
	return (uint64_t)(usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) * 1000 +
	       (uint64_t)(usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) / 1000;
}

/* The work; says which processor it found itself on at the end. */
static void *
work(void *arg)
{
	volatile uint64_t sum = 0;
	size_t cpu = 0;

	for (uint64_t i = 0; i < ROUNDS; i++) {
		sum += i * i;
	}
	pthread_cpu_number_np(&cpu);
	*(int *)arg = (int)cpu;
	return NULL;
}

/*
 * How fast each processor really runs: 100 additions each of which needs the one before, a million
 * times over, take 100 million cycles on any of these cores (one addition a cycle), whatever the
 * frequency table was asked for. As many threads as processors at once, so that every one is busy,
 * each says which processor it ran on and how many MHz it made.
 */
#define ADD10   "add %0, %0, #1\n\tadd %0, %0, #1\n\tadd %0, %0, #1\n\tadd %0, %0, #1\n\tadd %0, %0, #1\n\t" \
	        "add %0, %0, #1\n\tadd %0, %0, #1\n\tadd %0, %0, #1\n\tadd %0, %0, #1\n\tadd %0, %0, #1\n\t"
struct speed {
	uint64_t microseconds;
	size_t cpu;
};

static void *
speed(void *arg)
{
	struct speed *s = arg;
	uint64_t x = 0, t0, t1;
	static mach_timebase_info_data_t timebase;

	if (timebase.denom == 0) {
		mach_timebase_info(&timebase);
	}
	t0 = mach_absolute_time();
	for (unsigned i = 0; i < 1000000; i++) {
		__asm__ volatile (ADD10 ADD10 ADD10 ADD10 ADD10 ADD10 ADD10 ADD10 ADD10 ADD10 : "+r" (x));
	}
	t1 = mach_absolute_time();
	pthread_cpu_number_np(&s->cpu);
	s->microseconds = (t1 - t0) * timebase.numer / timebase.denom / 1000;
	return NULL;
}

static void
clock_speeds(int threads)
{
	pthread_t thread[MOST];
	struct speed result[MOST];

	for (int i = 0; i < threads; i++) {
		pthread_create(&thread[i], NULL, speed, &result[i]);
	}
	printf("cpu_test: clock (100 M dependent additions):");
	for (int i = 0; i < threads; i++) {
		pthread_join(thread[i], NULL);
		printf(" cpu%zu %llu MHz", result[i].cpu, result[i].microseconds ? 100000000ULL / result[i].microseconds : 0);
	}
	printf("\n");
}

int
main(int argc, char **argv)
{
	int active = number("hw.activecpu"), threads = active < 2 ? 2 : active > MOST ? MOST : active;
	int where[MOST], seen = 0;
	pthread_t thread[MOST];
	uint64_t start, alone, together, spent;

	if (argc > 1) {
		sleep((unsigned)atoi(argv[1]));
	}
	printf("cpu_test: hw.ncpu %d, hw.activecpu %d, hw.physicalcpu %d, hw.logicalcpu %d\n", number("hw.ncpu"),
	    number("hw.activecpu"), number("hw.physicalcpu"), number("hw.logicalcpu"));
	if (argc < 2) {
		return 0;
	}

	start = milliseconds();
	work(&where[0]);
	alone = milliseconds() - start;

	start = milliseconds();
	spent = used();
	for (int i = 0; i < threads; i++) {
		pthread_create(&thread[i], NULL, work, &where[i]);
	}
	for (int i = 0; i < threads; i++) {
		pthread_join(thread[i], NULL);
		seen |= 1 << where[i];
	}
	spent = used() - spent;
	together = milliseconds() - start;
	if (together == 0) {
		together = 1;
	}

	printf("cpu_test: one thread took %llu ms; %d threads at once took %llu ms and were given %llu ms of processor time: "
	    "%llu.%llu processors at work, seen on", alone, threads, together, spent, spent / together, spent * 10 / together % 10);
	for (int cpu = 0; cpu < 32; cpu++) {
		if (seen & (1 << cpu)) {
			printf(" %d", cpu);
		}
	}
	printf("\n");
	clock_speeds(threads);
	return 0;
}
