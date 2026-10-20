# C024: toolz.join

Outer joins emit already-matched left rows again as unmatched. Matched rows must appear only as matches; retain duplicate matches and supply defaults only for genuinely missing partners.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
