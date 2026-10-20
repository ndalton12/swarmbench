# C008: inflection.tableize

Model names ending in an irregular CamelCase noun produce the wrong table name. The result must be a snake-case plural table name based on the final word. Keep already underscored names working.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
