# C027: more_itertools.chunked

Strict chunking silently accepts a short trailing chunk. strict=True must raise ValueError when input length is not divisible by n, without changing non-strict chunking or exact batches.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
