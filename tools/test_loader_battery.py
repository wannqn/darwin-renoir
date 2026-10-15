#!/usr/bin/env python3
"""Execute the actual XNU battery-cache reader against valid, torn and invalid samples."""
from pathlib import Path
import subprocess, tempfile, re
r=Path(__file__).resolve().parents[1]
s=(r/'xnu/files/bsd/dev/redwood_battery.c').read_text()
a=s.index('#define LOADER_BATTERY_MAGIC')
b=s.index('SYSCTL_NODE',a)
state=s[a:b]
a=s.index('static bool\nbattery_snapshot(')
b=s.index('static void\nbattery_thread(',a)
helper=re.sub(r'__asm__ volatile \("dmb ishld" ::: "memory"\);', '(void)0;',s[a:b])
code="#include <stdint.h>\n#include <stdbool.h>\n#include <string.h>\n#include <assert.h>\n"+state+helper+r"""
int main(void) {
 struct loader_battery sample={.magic=LOADER_BATTERY_MAGIC,.version=1,.size=sizeof(sample),
 .sequence=2,.flags=LOADER_BATTERY_VALID|LOADER_BATTERY_PRESENT|LOADER_BATTERY_CHARGER_PRESENT|LOADER_BATTERY_CHARGING|LOADER_BATTERY_VOLTAGE_VALID,
 .soc_percent=87,.voltage_mv=3975,.current_ma=1170,.temperature_c=34};
 _Static_assert(sizeof(sample)==56,"loader/XNU ABI");
 shared_battery=&sample;
 battery_poll(); assert(battery_soc_percent==87 && battery_voltage_mv==3975);
 assert(battery_charging && battery_present && battery_charger_present && battery_updates==1);
 sample.sequence=3; battery_poll(); assert(battery_failures==1 && battery_updates==1);
 sample.sequence=4; sample.magic=0; battery_poll(); assert(battery_failures==2);
 sample.magic=LOADER_BATTERY_MAGIC; sample.soc_percent=101; battery_poll(); assert(battery_failures==3);
 sample.soc_percent=-1; battery_poll(); assert(battery_failures==4);
 sample.soc_percent=50; sample.flags=LOADER_BATTERY_VALID|LOADER_BATTERY_SOC_ESTIMATED;
 battery_poll(); assert(battery_soc_percent==50 && battery_soc_estimated && battery_voltage_mv==-1);
 assert(!battery_charging && !battery_charger_present && !battery_present);
 sample.flags=0; battery_poll(); assert(battery_failures==5 && battery_updates==2);
 return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='loader-battery-') as d:
 p=Path(d);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Werror','-Wno-unused-variable','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Battery cache: 56-byte ABI, valid/torn/invalid SOC and flags passed (host test does not verify ARM ordering)')
