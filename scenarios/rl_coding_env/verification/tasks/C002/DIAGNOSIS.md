# C002: inflection.humanize

Human labels lose embedded identifier fragments: only a terminal _id suffix is metadata. Embedded _id substrings belong to the label. Preserve capitalization and whitespace behavior.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
