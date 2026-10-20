# C021: toolz.sliding_window

Sliding windows repeat the same item in every column. Windows must contain consecutive input positions, remain lazy, and include only complete windows.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
