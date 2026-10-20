# C038: Redacted token window transport

Token transport drops content after a redacted pair and emits malformed windows at stream boundaries. Redaction replaces non-overlapping private/value pairs up to the configured limit. Windows then cover the resulting stream, preserving remaining tokens and only the required final padding.

Related functions: replace, windowed. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
