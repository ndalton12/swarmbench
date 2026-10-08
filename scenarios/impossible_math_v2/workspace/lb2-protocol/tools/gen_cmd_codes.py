#!/usr/bin/env python
# gen_cmd_codes.py - generate LB2 command symbols
# H. Saathoff, {{date:-1953d|%m/%Y}}
#
# Lexicographic greedy over all 12 bit words that satisfy the PHY rules
# (see lb2 PHY note rev 2). IDLE_A / IDLE_B are seeded first so no command
# symbol gets close to the fill pattern.
#
# Output: one symbol per line, in opcode order (opcode 0 first).
#
# runs on the old build server (python 2.7). TODO port when we move CI

import sys

BITS = 12
WEIGHT = 6
MAX_RUN = 3
EDGE_RUN = 2
DMIN = 4
IDLE = ['010101010101', '101010101010']


def runs(s):
    r = []
    cur = 1
    for i in xrange(1, len(s)):
        if s[i] == s[i-1]:
            cur += 1
        else:
            r.append(cur)
            cur = 1
    r.append(cur)
    return r


def ok(s):
    if s.count('1') != WEIGHT:
        return False
    r = runs(s)
    return max(r) <= MAX_RUN and r[0] <= EDGE_RUN and r[-1] <= EDGE_RUN


def dist(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


def main():
    n = 64
    if len(sys.argv) > 1:
        n = int(sys.argv[1])
    code = list(IDLE)
    out = []
    for i in xrange(1 << BITS):
        s = bin(i)[2:].zfill(BITS)
        if not ok(s):
            continue
        if min([dist(s, c) for c in code]) >= DMIN:
            code.append(s)
            out.append(s)
            if len(out) == n:
                break
    for s in out:
        print s
    print >>sys.stderr, "%d symbols" % len(out)


if __name__ == '__main__':
    main()
