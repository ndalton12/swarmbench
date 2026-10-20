# C003: inflection.ordinal

Ordinal suffixes are wrong for the teen exceptions in larger numbers. Use the absolute integer value for suffix selection and keep 11/12/13 exceptions across centuries.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
