# C012: inflection.dasherize

Only the first underscore is converted in multiword names. Replace every underscore, retaining all other characters, consecutive separators, and leading or trailing underscores.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
