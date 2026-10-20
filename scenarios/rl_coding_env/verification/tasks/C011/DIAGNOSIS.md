# C011: inflection.underscore

Acronyms are joined to the following CamelCase word when making snake case. Split the last acronym letter from the following lowercase run, while preserving ordinary lowercase-to-uppercase transitions and dashes.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
