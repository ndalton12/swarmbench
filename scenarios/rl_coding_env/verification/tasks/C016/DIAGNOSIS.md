# C016: toolz.tail

tail returns the beginning of generators instead of their last elements. For positive n, lists and one-shot iterables must agree, and iterators shorter than n should retain all their elements.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
