# C030: Consecutive ranges in threshold batches

Range batches fragment consecutive identifiers and omit the range that starts the next batch. Identifiers are grouped by consecutive numeric value while retaining their original spelling. The first range at or beyond the threshold belongs at the start of the final batch.

Related functions: split_before, consecutive_groups. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
