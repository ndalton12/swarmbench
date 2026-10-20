# C032: more_itertools.padded

Padding truncates input longer than n. n is a minimum length, not a maximum; return all original items and add fill values only if necessary. Keep next_multiple behavior intact.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
