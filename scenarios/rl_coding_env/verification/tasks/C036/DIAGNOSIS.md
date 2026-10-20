# C036: more_itertools.consecutive_groups

Consecutive grouping ignores adjacency when an ordering function is supplied. Values whose ordinals differ by one belong in the same group; retain the original values in each group.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
