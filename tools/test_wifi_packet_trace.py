#!/usr/bin/env python3
"""Check opt-in packet-header diagnostics against short and malformed frames."""
from pathlib import Path
import subprocess
import struct
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'wifi/lx/src/lx_80211.c').read_text()
start = source.index('static unsigned\npacket_sum(')
function = source[start:source.index('/* An Ethernet frame, through', start)]
def checksum(data):
    data += b'\0' * (len(data) % 2)
    total = sum(struct.unpack('!' + 'H' * (len(data) // 2), data))
    while total >> 16:
        total = (total & 65535) + (total >> 16)
    return (~total) & 65535

own = b'\x02' + bytes(5)
bootp = bytearray(240)
bootp[:3] = b'\x01\x01\x06'
bootp[28:34] = own
bootp[236:240] = bytes([99, 130, 83, 99])
bootp += bytes([53, 1, 1, 61, 7, 1]) + own + b'\xff'
addresses = bytes(4) + b'\xff' * 4
udp = struct.pack('!HHHH', 68, 67, 8 + len(bootp), 0) + bootp
pseudo = addresses + struct.pack('!BBH', 0, 17, len(udp))
udp = udp[:6] + struct.pack('!H', checksum(pseudo + udp) or 65535) + udp[8:]
ip = struct.pack('!BBHHHBBH', 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0) + addresses
ip = ip[:10] + struct.pack('!H', checksum(ip)) + ip[12:]
fixture = b'\xff' * 6 + own + b'\x08\x00' + ip + udp
declaration = 'static const uint8_t dhcp[]={' + ','.join(map(str, fixture)) + '};\n'
code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#define ETH_ALEN 6
struct lx_radio {struct {uint8_t addr[6];} *vif;};
static bool enabled;static unsigned printed;static char line[256];
static bool lx_os_option(const char *s){assert(!strcmp(s,"wifi_trace"));return enabled;}
static void lx_tell(const char *format,...){va_list ap;va_start(ap,format);vsnprintf(line,sizeof(line),format,ap);va_end(ap);printed++;}
''' + function + declaration + r'''
int main(void){
 struct lx_radio r={0};typeof(*r.vif) vif={{2}};r.vif=&vif;
 uint8_t frame[64]={0};memcpy(frame+6,vif.addr,6);frame[12]=8;frame[14]=0x45;frame[23]=17;
 frame[34]=0;frame[35]=68;frame[36]=0;frame[37]=67;frame[39]=9;frame[42]=1;
 ethernet_trace(&r,frame,43,true);assert(!printed);
 enabled=true;ethernet_trace(&r,frame,43,true);
 assert(strstr(line,"source-is-station 1 UDP 68->67 BOOTP 0"));
 frame[21]=1;ethernet_trace(&r,frame,43,true);assert(strstr(line,"UDP 0->0 BOOTP 0"));frame[21]=0;
 uint8_t packet[sizeof(dhcp)];memcpy(packet,dhcp,sizeof(packet));
 ethernet_trace(&r,packet,sizeof(packet),true);
 assert(strstr(line,"checksums 1/1 DHCP 1 chaddr 1 client-id 1 broadcast 0"));
 packet[40]^=1;ethernet_trace(&r,packet,sizeof(packet),true);assert(strstr(line,"checksums 1/0"));
 packet[40]^=1;packet[24]^=1;ethernet_trace(&r,packet,sizeof(packet),true);assert(strstr(line,"checksums 0/1"));
 for(unsigned n=0;n<64;n++)for(unsigned ihl=0;ihl<16;ihl++){
  uint8_t exact[64];memcpy(exact,frame,sizeof(frame));exact[14]=0x40|ihl;
  ethernet_trace(&r,exact,n,false);
 }
 assert(printed<=128);
}
'''
with tempfile.TemporaryDirectory(prefix='wifi-packet-trace-') as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(code)
    subprocess.run(['clang', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'test.c'), '-o', str(path / 'test')], check=True)
    subprocess.run([str(path / 'test')], check=True)
print('Packet diagnostics: disabled by default, DHCP headers, fragment exclusion, short/invalid headers and log bounds passed')
