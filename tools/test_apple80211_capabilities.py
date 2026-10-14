#!/usr/bin/env python3
"""Exercise the real 13-byte Apple80211 capability response for mixed CCMP/TKIP RSN."""
from pathlib import Path
import subprocess,tempfile
s=(Path(__file__).resolve().parents[1]/'xnu/files/bsd/dev/redwood_apple80211.c').read_text()
a=s.index('case 12: {',s.index('static int\nget('))+len('case 12: {')
b=s.index('\n\t}\n\tcase 19:',a)
code=r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
static uint8_t answer[13];
static int give(void *request,const void *data,unsigned size){
 assert(request && size==13);memcpy(answer,data,size);return 0;
}
static int capabilities(void *request){
"""+s[a:b]+r"""
}
static unsigned bit(unsigned n){return answer[n/8]>>(n%8)&1;}
int main(void){
 int request;assert(capabilities(&request)==0);
 /* External Apple80211 ABI: TKIP=1, AES-CCM=3, TKIPMIC=12, WPA2=14. */
 assert(bit(1) && bit(3) && bit(12) && bit(14));
 assert(!bit(0) && !bit(13)); /* do not advertise WEP/WPA1 */
 for(unsigned i=3;i<13;i++) assert(answer[i]==0);
 return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='apple80211-capabilities-') as tmp:
 p=Path(tmp);(p/'test.c').write_text(code)
 subprocess.run(['clang','-Wall','-Wextra','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
print('Apple80211 capability ABI: TKIP GTK/MIC, CCMP/WPA2, 13-byte response, no WEP/WPA1 passed')
