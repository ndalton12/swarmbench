# C013: toolz.unique

Deduplication with a key function keeps repeated logical keys. Preserve the first original item for each key, in input order, including when input items themselves are unhashable.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
