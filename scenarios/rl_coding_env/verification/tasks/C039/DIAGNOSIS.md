# C039: more_itertools.is_sorted

Descending order checks use the ascending comparison. reverse=True should accept non-increasing input, with strict=True rejecting equal neighboring keys. Keep key functions and empty input behavior.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
