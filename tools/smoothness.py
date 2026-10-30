#!/usr/bin/env python3
"""
smoothness.py RUN.log [MORE.log ...]: how many refreshes the panel missed while something was moving,
and which stage of the pipeline each miss belongs to.

Reads the "tl:" lines of a run with boot-arg touch_lat=1 (see tools/latency.py): the touches of
rwtouch (tl: p), SpringBoard's main run loop turns (tl: a, userland/src/inject_sb.c), the window
server's frames (tl: g), their hand-over (tl: s) and the display driver's frames (tl: v). Only the
WINDOW (default 0.7 s) after each touch going down is counted: the gesture and its main animation.
Later frames come when something changes, at whatever pace that is, and are not a missed refresh.

Every gap of more than 25 ms between two frames on the panel is one or more missed refreshes
(round(gap / 16.7 ms) - 1), charged to the stage that held the frame that ended it:

  SpringBoard busy   the window server began no frame for over a refresh, and SpringBoard's main
                     thread was in a turn of over a refresh meanwhile
  no update          the window server began no frame, SpringBoard was not busy (an application's
                     own main thread, or nothing to show)
  render CPU         the window server's drawing of it (first draw to glFlush done: Mesa included)
  GPU                hand-over to the GPU being done with it
  present            the display driver putting it on the panel

This is the measure the latency work of 30 October 2026 used (rc.jobs.latency-bench). tools/frames.py
counts every frame-to-frame time over 16.7 ms instead, which uneven but complete pacing inflates.
"""
import argparse
import bisect
import collections

REFRESH_US = 16667


def parse(path):
    turns, draws, shown, downs, swaps = [], [], [], [], {}
    with open(path, 'rb') as f:
        for raw in f:
            w = raw.decode('utf-8', 'replace').split()
            try:
                if w[:2] == ['tl:', 'a'] and len(w) >= 5:
                    turns.append((int(w[2]), int(w[4])))
                elif w[:2] == ['tl:', 'g'] and len(w) >= 8 and w[3] == 'began':
                    draws.append((int(w[4]), int(w[6])))
                elif w[:2] == ['tl:', 'v'] and len(w) >= 9:
                    shown.append((int(w[2]), int(w[4]), int(w[6]), int(w[8])))
                elif w[:2] == ['tl:', 's'] and len(w) >= 5:
                    swaps[int(w[2])] = int(w[4])
                elif w[:3] == ['tl:', 'p', '1'] and len(w) >= 8:
                    downs.append(int(w[7]))
            except (ValueError, IndexError):
                pass                    # (a line two writers interleaved)
    shown.sort(key=lambda v: v[3])
    draws.sort()
    downs.sort()
    return turns, draws, shown, downs, swaps


def analyze(path, window_us):
    turns, draws, shown, downs, swaps = parse(path)
    began = [d[0] for d in draws]
    steps, charged, gaps = [], collections.Counter(), collections.Counter()
    for i in range(1, len(shown)):
        t0, t1 = shown[i - 1][3], shown[i][3]
        gap = t1 - t0
        k = bisect.bisect_right(downs, t0) - 1
        if gap > 300000 or k < 0 or t0 - downs[k] > window_us:
            continue
        steps.append(gap)
        if gap <= 25000:
            continue
        swap_id, ready, start, done = shown[i]
        handed = swaps.get(swap_id, t1)
        j = bisect.bisect_right(began, handed) - 1
        draw_began, draw_ended = draws[j] if j >= 0 else (t1, t1)
        if draw_began - t0 > REFRESH_US:
            busy = any(e - w > REFRESH_US and w < draw_began and e > t0 - REFRESH_US for w, e in turns)
            stage = 'SpringBoard busy' if busy else 'no update'
        else:
            costs = {'render CPU': draw_ended - draw_began, 'GPU': ready - handed, 'present': done - start}
            stage = max(costs, key=costs.get)
        charged[stage] += round(gap / REFRESH_US) - 1
        gaps[stage] += 1
    return steps, charged, gaps


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('logs', nargs='+')
    ap.add_argument('--window', type=float, default=0.7, help='seconds after each touch going down (0.7)')
    args = ap.parse_args()
    for path in args.logs:
        steps, charged, gaps = analyze(path, int(args.window * 1e6))
        if not steps:
            print(f'{path}: no frames inside any gesture window (was touch_lat=1 set?)')
            continue
        missed = sum(charged.values())
        print(f'{path}: {len(steps)} frames in gestures at {len(steps) / (sum(steps) / 1e6):.1f} a second; '
              f'{missed} refreshes missed ({100 * missed / (len(steps) + missed):.1f}%); '
              f'{100 * sum(g > 50000 for g in steps) / len(steps):.1f}% of gaps over 50 ms, the longest {max(steps) // 1000} ms')
        for stage, n in charged.most_common():
            print(f'  {stage:16s} {n:4d} missed in {gaps[stage]:3d} gaps ({100 * n / max(missed, 1):.0f}%)')


if __name__ == '__main__':
    main()
