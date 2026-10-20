# C039: Balanced ordered partition audit

Partition audits depend on reader order and reject correctly descending blocks. Each balanced contiguous partition must retain its assigned values independently. Ordering checks apply to those values with the configured tie policy, rather than changing the allocation or reversing the contract.

Related functions: is_sorted, divide. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
