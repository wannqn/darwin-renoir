#!/usr/bin/env python3
"""Exercise the real RAMFS table-growth code with XNU's large/NOWAIT rule."""
from pathlib import Path
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[1]
source = (repo / 'xnu/files/bsd/miscfs/ramfs/ramfs.c').read_text()
start = source.index('static int\nramfs_grow_slots(')
end = source.index('/*\n * Copy len bytes', start)
helper = source[start:end]
test = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
enum { Z_WAITOK = 1, Z_NOWAIT = 2, Z_ZERO = 4 };
struct ramfs_mount { int rm_lock; };
struct ramfs_node { struct ramfs_mount *rn_mount; uint64_t rn_nslots, rn_ino; void **rn_pages; };
static int held = 1, allocations, fail, concurrent;
static struct ramfs_node *current;
static void lck_mtx_unlock(int *lock) { (void)lock; assert(held); held = 0; }
static void lck_mtx_lock(int *lock) { (void)lock; assert(!held); held = 1; }
static void **allocate_slots(uint64_t count, int flags) {
    allocations++;
    if (flags & Z_WAITOK) assert(!held); else assert(held);
    if (fail || ((flags & Z_NOWAIT) && count * sizeof(void *) >= 32768)) return NULL;
    if (concurrent) {
        void **other = calloc(16384, sizeof(void *)); assert(other);
        memcpy(other, current->rn_pages, current->rn_nslots * sizeof(void *));
        free(current->rn_pages); current->rn_pages = other; current->rn_nslots = 16384;
        concurrent = 0;
    }
    return calloc(count, sizeof(void *));
}
#define kalloc_type(type, count, flags) allocate_slots(count, flags)
#define kfree_type(type, count, ptr) free(ptr)
''' + helper + r'''
int main(void) {
    struct ramfs_mount mount = {0};
    struct ramfs_node node = { .rn_mount = &mount, .rn_nslots = 4, .rn_ino = 1 };
    node.rn_pages = calloc(4, sizeof(void *)); assert(node.rn_pages);
    node.rn_pages[0] = (void *)0x1234; current = &node;
    assert(ramfs_grow_slots(&node, 4096, true) == 0);
    assert(held && node.rn_nslots == 8192 && node.rn_pages[0] == (void *)0x1234);
    int before = allocations;
    assert(ramfs_grow_slots(&node, 4096, false) == 0 && allocations == before);
    free(node.rn_pages); node.rn_pages = calloc(4, sizeof(void *)); node.rn_nslots = 4;
    node.rn_pages[0] = (void *)0x5678; concurrent = 1;
    assert(ramfs_grow_slots(&node, 4096, true) == 0);
    assert(held && node.rn_nslots == 16384 && node.rn_pages[0] == (void *)0x5678);
    free(node.rn_pages); node.rn_pages = calloc(4, sizeof(void *)); node.rn_nslots = 4;
    assert(ramfs_grow_slots(&node, 4096, false) == ENOSPC && held && node.rn_nslots == 4);
    fail = 1;
    assert(ramfs_grow_slots(&node, 4096, true) == ENOMEM && held && node.rn_nslots == 4);
    assert(ramfs_grow_slots(&node, UINT64_MAX, true) == EFBIG && held);
    free(node.rn_pages);
    return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'slots.c').write_text(test)
    subprocess.run(['clang', '-Wall', '-Werror', '-Wno-format', '-fsanitize=address,undefined',
                    str(root / 'slots.c'), '-o', str(root / 'slots')], check=True)
    subprocess.run([str(root / 'slots')], check=True)
print('RAMFS growth: allocation, pager, concurrent growth, failure and overflow checks passed')
