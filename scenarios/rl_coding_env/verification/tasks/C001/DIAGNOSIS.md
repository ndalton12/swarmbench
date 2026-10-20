# C001: inflection.camelize

Lower camel case leaves underscores in compound identifiers. Respect uppercase_first_letter=False without losing the capital boundaries of later words. Keep the existing upper-camel behavior and acronym conventions.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
