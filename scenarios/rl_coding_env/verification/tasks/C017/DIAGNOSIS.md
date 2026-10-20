# C017: toolz.get

Selecting a single index using a list of indices drops the tuple shape. List-index requests always return a tuple, including empty and singleton selections. Scalar indexing and defaults retain their existing behavior.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
