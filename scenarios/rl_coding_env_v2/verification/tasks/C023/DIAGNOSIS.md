# C023: Projected group totals and membership

Group exports disagree between their projected rows, totals and membership lists. Projection must keep distinct field values, every row contributes once to its group total, and membership lists remain independent even when groups are interleaved in the source.

Related functions: pluck, reduceby. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
