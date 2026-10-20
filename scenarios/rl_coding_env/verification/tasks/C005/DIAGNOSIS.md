# C005: inflection.parameterize

Single-character punctuation separators behave like regular expressions and collapse unrelated characters. Treat separators literally, keep transliteration and trim only the selected separator at the ends. The empty separator must still remove punctuation.

The baseline mutation is confined to `inflection/__init__.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
