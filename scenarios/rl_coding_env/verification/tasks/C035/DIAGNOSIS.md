# C035: more_itertools.always_iterable

Strings and bytes are unexpectedly expanded into characters instead of one value. The default base_type treats text as atomic, whereas base_type=None should allow ordinary iteration. Preserve scalar and None handling.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
