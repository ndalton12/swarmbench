# C009: inflection.titleize

CamelCase names are not separated when producing human titles. Apply word-boundary normalization before title capitalization, retaining apostrophe and underscore behavior.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
