# C024: First-record reconciliation join

Reconciliation emits repeated logical entries and marks already matched entries as unmatched. The first input row for each key is authoritative. It participates in every legitimate lookup match, while only keys absent from the lookup receive a missing-partner record.

Related functions: join, unique. The faithful repair restores their
pinned implementations. `workflow.py` composes them in a concrete caller. Each
partial repair is checked against live and independent workflow inputs; three-function
tasks include both only-one-repaired and leave-one-broken variants.

No residual acceptance defect is intended.
