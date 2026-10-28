/*
 * Renoir haptics bridge (PM8350B, bsd/dev/renoir_haptic.c).
 */
#include <stdbool.h>
#include <stdint.h>
#include <sys/types.h>

extern void renoir_haptic_init(void);
extern void renoir_haptic_quiesce(void);

void
redwood_haptic_init(void)
{
	renoir_haptic_init();
}

void
redwood_haptic_quiesce(void)
{
	renoir_haptic_quiesce();
}
