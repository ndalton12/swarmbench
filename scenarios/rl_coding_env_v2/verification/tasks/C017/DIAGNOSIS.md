# C017: Projected row selection API

The projected-row selection API changes its response shape for a single requested row and returns repeated columns. A list of requested row positions always produces a sequence of rows, even for one position. Each row preserves the requested group/value column order and default values.

Related functions: get, pluck. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
