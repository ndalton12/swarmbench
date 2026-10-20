# C023: toolz.pluck

Multi-column pluck with a default repeats the first column. Respect each requested key independently, using the default only when that field is absent, and retain tuple field ordering.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
