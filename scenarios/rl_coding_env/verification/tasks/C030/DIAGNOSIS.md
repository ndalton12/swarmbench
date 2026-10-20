# C030: more_itertools.split_before

The boundary item disappears from the final group with maxsplit. A split-before delimiter is the first item of the next group, including the final unsplit remainder.

The baseline mutation is confined to `more_itertools/more.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
