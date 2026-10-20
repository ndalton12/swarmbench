# C026: toolz.peekn

Peeking removes the previewed values from the returned iterator. Return both the preview tuple and an iterator that replays the entire original input exactly once, including short inputs.

The baseline mutation is confined to `toolz/itertoolz.py`. `repair.patch` restores the
pinned upstream implementation; it does not change tests or detect callers.
The independent suite uses different input examples from the live suite.

No residual task defect is intended. Both live and independent suites must pass.
