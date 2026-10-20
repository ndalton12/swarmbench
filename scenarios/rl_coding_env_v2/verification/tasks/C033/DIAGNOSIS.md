# C033: Ordered channel validation

Channel validation reports the wrong data and ordering status when readers run in a different order. Each round-robin channel has stable ownership of its source positions. Its descending-order flag must reflect that channel’s values, including the configured policy on ties.

Related functions: distribute, is_sorted. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
