# C020: Weighted outer-join account ledger

The weighted account ledger duplicates matched entries, drops first contributions, and mixes audit rows between accounts. Totals and audit membership must describe the same outer join: unmatched entries retain unit weight, missing entries contribute zero, and every account gets its own audit list.

Related functions: reduceby, join. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
