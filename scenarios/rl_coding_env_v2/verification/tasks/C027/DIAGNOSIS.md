# C027: Striped strict transport framing

Striped transport frames depend on which channel is read first, and incomplete frames sometimes escape strict validation. Each source position belongs to one round-robin channel independent of consumption order. Every emitted frame must have the configured width, with incomplete input rejected.

Related functions: chunked, distribute. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
