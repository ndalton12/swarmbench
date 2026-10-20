# C013: First-seen grouped projection export

The grouped projection export repeats logical groups and assigns the wrong values to columns. The first complete projected row for each case-insensitive group is retained, in source order. Missing value fields use zero; the group and value columns have distinct meanings.

Related functions: unique, pluck. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
