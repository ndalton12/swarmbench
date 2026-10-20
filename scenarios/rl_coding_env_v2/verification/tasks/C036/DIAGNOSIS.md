# C036: Range batches with a closing range

Range batches lose grouping and repeat their closing range in the following batch. Numeric adjacency determines each range, preserving original labels. The first range meeting the size threshold closes its batch and must not appear again in the remainder.

Related functions: consecutive_groups, split_after. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
