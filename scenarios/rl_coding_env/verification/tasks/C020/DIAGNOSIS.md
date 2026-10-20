# C020: toolz.reduceby

Grouped reduction with an initial value skips the first item of each group. Apply the reducer to every item exactly once. Call a supplied initializer function once per new key, and preserve the no-initial behavior.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
