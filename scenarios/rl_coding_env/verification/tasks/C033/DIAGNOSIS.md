# C033: more_itertools.distribute

Round-robin distribution repeats the first child stream in every bucket. Each input position belongs to exactly one child based on its position modulo n. Preserve child order and uneven lengths.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
