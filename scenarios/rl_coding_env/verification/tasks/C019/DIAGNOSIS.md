# C019: toolz.frequencies

Frequency counts stop at one despite repeated input. Accumulate the full count for each hashable item while consuming generators once. Preserve distinctions between separate keys.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
