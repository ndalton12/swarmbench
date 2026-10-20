# C006: inflection.pluralize

Uppercase uncountable nouns acquire plural suffixes. Uncountability is case insensitive; preserve the original casing rather than normalizing the returned word. Ordinary inflection rules must still apply.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
