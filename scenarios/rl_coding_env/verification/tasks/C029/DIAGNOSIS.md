# C029: more_itertools.split_at

The separator reappears in the tail after maxsplit is reached. Separator items are excluded unless keep_separator is requested; the unsplit remainder starts after the delimiter that used the last split.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
