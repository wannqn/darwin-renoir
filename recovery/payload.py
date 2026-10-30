"""Validate and update a RAM boot container without modifying archived inputs."""
import re
import struct


def validate_mac(value):
    value = value.strip().lower()
    if re.fullmatch(r'[0-9a-f]{12}', value):
        value = ':'.join(value[index:index + 2] for index in range(0, 12, 2))
    elif not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', value):
        raise ValueError('Wi-Fi MAC must be 12 hexadecimal digits; colons are optional')
    address = bytes.fromhex(value.replace(':', ''))
    if address[0] & 1 or not any(address):
        raise ValueError('Wi-Fi MAC must be a nonzero unicast address')
    return value


def validate_apfs(header, image_size):
    """Validate the raw 4 KiB APFS container superblock before any USB operation."""
    if len(header) < 4096 or header[32:36] != b'NXSB':
        raise ValueError('Expected a raw APFS container (NXSB), not a legacy packfs image')
    block_size, blocks = struct.unpack_from('<IQ', header, 36)
    if block_size != 4096 or blocks < 1 or blocks * block_size != image_size:
        raise ValueError('Invalid APFS block size or container length')
    first = second = 0
    for word in struct.unpack_from('<1022I', header, 8):
        first = (first + word) % 0xffffffff
        second = (second + first) % 0xffffffff
    low = 0xffffffff - (first + second) % 0xffffffff
    high = 0xffffffff - (first + low) % 0xffffffff
    if struct.unpack_from('<Q', header)[0] != (high << 32) | low:
        raise ValueError('Invalid APFS container superblock checksum')


def prepare(data, epoch, wifi_mac=None, kernel=None, cpu_count=None, ramdisk=None, boot_args=()):
    """boot_args: extra words for the kernel command line; each replaces any word of the same name."""
    for arg in boot_args:
        if not arg or any(c.isspace() for c in arg) or arg.startswith('='):
            raise ValueError('Invalid boot argument: ' + repr(arg))
    if len(data) < 8:
        raise ValueError('Truncated XNUP header')
    magic, size = struct.unpack_from('<II', data)
    if magic != 0x50554e58 or size != len(data) - 8:
        raise ValueError('Invalid XNUP header or size')
    if wifi_mac is not None:
        wifi_mac = validate_mac(wifi_mac)
    if ramdisk is not None:
        validate_apfs(ramdisk[:4096], len(ramdisk))
    entries = []
    offset = 8
    terminated = False
    names = set()
    while offset + 24 <= len(data):
        name, size, reserved = struct.unpack_from('<16sII', data, offset)
        offset += 24
        key = name.rstrip(b'\0')
        if not key:
            if size or reserved or offset != len(data):
                raise ValueError('Invalid XNUP terminator')
            terminated = True
            break
        if key in names:
            raise ValueError('Duplicate XNUP entry')
        names.add(key)
        end = offset + ((size + 15) & ~15)
        if end > len(data):
            raise ValueError('Truncated XNUP entry')
        body = data[offset:offset + size]
        offset = end
        if key == b'cmdline':
            words = body.rstrip(b'\0').decode().split()
            replaced = ('epoch=',) if wifi_mac is None else ('epoch=', 'wifi_mac=')
            if cpu_count is not None:
                replaced += ('cpus=',)
            words = [word for word in words if not word.startswith(replaced)]
            if cpu_count is not None:
                words.append('cpus=' + str(cpu_count))
            words.append('epoch=' + str(int(epoch)))
            if wifi_mac is not None:
                words.append('wifi_mac=' + wifi_mac)
            for arg in boot_args:
                arg_name = arg.split('=', 1)[0]
                words = [word for word in words if word.split('=', 1)[0] != arg_name] + [arg]
            body = ' '.join(words).encode() + b'\0'
        elif key == b'kernel' and kernel is not None:
            if not kernel:
                raise ValueError('Replacement kernel is empty')
            body = kernel
        elif key == b'ramdisk' and ramdisk is not None:
            body = ramdisk
        entries.append(struct.pack('<16sII', name, len(body), reserved)
                       + body + b'\0' * (-len(body) % 16))
    if not terminated or b'cmdline' not in names or b'kernel' not in names:
        raise ValueError('XNUP requires a terminator, cmdline and kernel')
    if ramdisk is not None and b'ramdisk' not in names:
        raise ValueError('XNUP has no ramdisk to replace')
    body = b''.join(entries) + b'\0' * 24
    return struct.pack('<II', magic, len(body)) + body
