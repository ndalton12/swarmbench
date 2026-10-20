# C038: more_itertools.replace

Pattern replacement removes the item following a matched multi-item window. The next non-overlapping input item must remain in the output. Respect the replacement count and reusable substitutes.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
