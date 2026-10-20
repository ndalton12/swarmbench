# C032: Minimum-capacity balanced block assignment

Balanced block assignments truncate input above minimum capacity and depend on block read order. Capacity is a lower bound: retain all source items and add zeros only if needed. Blocks remain contiguous, differ in length by at most one, and retain their assigned contents regardless of consumption order.

Related functions: padded, divide. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
